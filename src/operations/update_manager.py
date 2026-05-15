from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.competition.config_manager import detect_code_version
from src.config import PROJECT_ROOT, Settings, load_settings, settings_hash
from src.storage.repository import ArenaRepository


UPDATE_TYPES = {"CONFIG_RELOAD", "PROMPT_UPDATE", "RULEBOOK_UPDATE", "CODE_RESTART", "ROLLBACK"}


@dataclass(frozen=True)
class UpdateValidation:
    passed: bool
    checks: dict[str, str]


class LiveUpdateManager:
    def __init__(self, settings: Settings, repository: ArenaRepository, project_root: Path = PROJECT_ROOT) -> None:
        self.settings = settings
        self.repository = repository
        self.project_root = project_root
        self.state_dir = project_root / "state"
        self.checkpoint_dir = self.state_dir / "checkpoints"
        self.backup_dir = self.state_dir / "backups"
        self.queue_path = self.state_dir / "update_queue.json"
        self.versions_path = self.state_dir / "active_versions.json"
        self.restart_path = self.state_dir / "restart_requested.json"
        self.last_restart_path = self.state_dir / "last_successful_restart.json"
        self.log_path = project_root / "logs" / "update_manager.log"

    def ensure_storage(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.queue_path.exists():
            self._write_json(self.queue_path, [])
        if not self.versions_path.exists():
            self._write_json(self.versions_path, self.current_versions())
        else:
            self._refresh_active_versions()

    def current_versions(self) -> dict[str, Any]:
        prompt_path = self.project_root / "prompts" / "system_prompt.md"
        rulebook_path = self.settings.resolve_path(self.settings.paths.rulebook)
        return {
            "code_version": detect_code_version(self.project_root),
            "config_version": _settings_hash_or_empty(self.project_root / "config" / "settings.yaml"),
            "system_prompt": {
                "path": str(prompt_path.relative_to(self.project_root)) if prompt_path.exists() else "prompts/system_prompt.md",
                "hash": _sha256_file(prompt_path),
            },
            "rulebook": {
                "path": str(rulebook_path.relative_to(self.project_root)) if rulebook_path.exists() and rulebook_path.is_relative_to(self.project_root) else str(rulebook_path),
                "hash": _sha256_file(rulebook_path),
            },
            "updated_at": _now_iso(),
        }

    def _refresh_active_versions(self) -> None:
        stored = _read_json(self.versions_path, {})
        current = self.current_versions()
        for key, value in stored.items():
            if key.startswith("canary_"):
                current[key] = value
        comparable_keys = ("code_version", "config_version", "system_prompt", "rulebook")
        if any(stored.get(key) != current.get(key) for key in comparable_keys):
            self._write_json(self.versions_path, current)

    def queue_update(self, update_type: str, payload: dict[str, Any] | None = None) -> str:
        self.ensure_storage()
        normalized = update_type.upper()
        if normalized not in UPDATE_TYPES:
            raise ValueError(f"unsupported update type: {update_type}")
        entry = {
            "id": uuid4().hex,
            "type": normalized,
            "requested_at": _now_iso(),
            "status": "PENDING",
            "payload": payload or {},
        }
        queue = self.read_queue()
        queue.append(entry)
        self._write_json(self.queue_path, queue)
        self.audit("QUEUED", normalized, f"Queued update {entry['id']}", {"id": entry["id"], "payload": payload or {}})
        return str(entry["id"])

    def read_queue(self) -> list[dict[str, Any]]:
        self.ensure_storage()
        try:
            data = json.loads(self.queue_path.read_text(encoding="utf-8"))
        except Exception:
            data = []
        return data if isinstance(data, list) else []

    def pending_updates(self) -> list[dict[str, Any]]:
        return [entry for entry in self.read_queue() if entry.get("status") == "PENDING"]

    def mark_update(self, update_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        queue = self.read_queue()
        for entry in queue:
            if entry.get("id") == update_id:
                entry["status"] = status
                entry["processed_at"] = _now_iso()
                entry["result"] = result or {}
                break
        self._write_json(self.queue_path, queue)

    def validate_update(self, run_smoke: bool = False) -> UpdateValidation:
        checks: dict[str, str] = {}
        try:
            load_settings(self.project_root / "config" / "settings.yaml")
            checks["config_schema"] = "PASS"
        except Exception as error:
            checks["config_schema"] = f"FAIL: {error}"
        prompt = self.project_root / "prompts" / "system_prompt.md"
        checks["prompt_file"] = "PASS" if prompt.exists() and prompt.read_text(encoding="utf-8").strip() else "FAIL: prompts/system_prompt.md is empty or missing"
        rulebook = self.settings.resolve_path(self.settings.paths.rulebook)
        checks["rulebook"] = "PASS" if rulebook.exists() and rulebook.read_text(encoding="utf-8").strip() else f"FAIL: {rulebook} is empty or missing"
        checks["checkpoint"] = "PASS" if (self.checkpoint_dir / "latest.json").exists() or self.repository.latest_checkpoint() else "FAIL: no checkpoint available"
        if run_smoke:
            result = subprocess.run(
                [str(Path.cwd() / ".venv" / "Scripts" / "python.exe") if (Path.cwd() / ".venv" / "Scripts" / "python.exe").exists() else "python", "-m", "compileall", "src"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
            )
            checks["smoke_tests"] = "PASS" if result.returncode == 0 else f"FAIL: {result.stderr.strip() or result.stdout.strip()}"
        passed = all(value == "PASS" for value in checks.values())
        return UpdateValidation(passed=passed, checks=checks)

    def write_checkpoint_file(self, payload: dict[str, Any], checkpoint_id: int, cycle_number: int, status: str) -> Path:
        self.ensure_storage()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        deployment = self.deployment_state()
        document = {
            "checkpoint_id": checkpoint_id,
            "cycle_number": cycle_number,
            "status": status,
            "written_at": _now_iso(),
            "payload": payload,
            "deployment": deployment,
        }
        path = self.checkpoint_dir / f"{timestamp}-cycle-{cycle_number}.json"
        self._write_json(path, document)
        self._write_json(self.checkpoint_dir / "latest.json", document)
        self.audit("CHECKPOINT", "FILESYSTEM_CHECKPOINT", f"Wrote checkpoint {path.name}", {"cycle_number": cycle_number, "status": status})
        return path

    def latest_checkpoint_file(self) -> dict[str, Any]:
        self.ensure_storage()
        path = self.checkpoint_dir / "latest.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def backup_current_state(self, reason: str) -> Path:
        self.ensure_storage()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = self.backup_dir / f"{stamp}-{_safe_name(reason)}"
        target.mkdir(parents=True, exist_ok=True)
        for source in [
            self.project_root / "config" / "settings.yaml",
            self.project_root / "prompts" / "system_prompt.md",
            self.settings.resolve_path(self.settings.paths.rulebook),
            self.checkpoint_dir / "latest.json",
        ]:
            if source.exists():
                shutil.copy2(source, target / source.name)
        db_path = self.settings.resolve_path(self.settings.paths.database)
        if db_path.exists():
            shutil.copy2(db_path, target / db_path.name)
        self._write_json(target / "versions.json", self.current_versions())
        self.audit("BACKUP", reason, f"Backed up state to {target}", {"path": str(target)})
        return target

    def apply_file_update(self, update_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        source_value = payload.get("version_path") or payload.get("source_path") or payload.get("path")
        if not source_value:
            raise ValueError(f"{update_type} requires source_path/version_path")
        source = Path(str(source_value))
        if not source.is_absolute():
            source = self.project_root / source
        if not source.exists() or not source.read_text(encoding="utf-8").strip():
            raise ValueError(f"update file is missing or empty: {source}")
        if update_type == "PROMPT_UPDATE":
            target_agents = [str(agent) for agent in payload.get("target_agents", []) if str(agent)]
            if target_agents:
                versions = _read_json(self.versions_path, self.current_versions())
                canary_prompts = versions.setdefault("canary_prompts", {})
                for agent_id in target_agents:
                    canary_prompts[agent_id] = {
                        "path": str(source.relative_to(self.project_root)) if source.is_relative_to(self.project_root) else str(source),
                        "hash": _sha256_file(source),
                        "activated_at": _now_iso(),
                    }
                versions["updated_at"] = _now_iso()
                self._write_json(self.versions_path, versions)
                self.audit("APPLIED", update_type, f"Activated canary prompt {source}", {"target_agents": target_agents})
                return {"source": str(source), "target_agents": target_agents, "versions": versions}
            destination = self.project_root / "prompts" / "system_prompt.md"
        elif update_type == "RULEBOOK_UPDATE":
            destination = self.settings.resolve_path(self.settings.paths.rulebook)
        else:
            raise ValueError(f"unsupported file update: {update_type}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        versions = self.current_versions()
        self._write_json(self.versions_path, versions)
        self.audit("APPLIED", update_type, f"Copied {source} to {destination}", {"target_agents": payload.get("target_agents", [])})
        return {"source": str(source), "destination": str(destination), "versions": versions}

    def rollback_from_backup(self, backup_path: str | None = None) -> dict[str, Any]:
        self.ensure_storage()
        backup = Path(backup_path) if backup_path else self.latest_backup()
        if not backup or not backup.exists():
            raise RuntimeError("no backup available for rollback")
        mapping = {
            "settings.yaml": self.project_root / "config" / "settings.yaml",
            "system_prompt.md": self.project_root / "prompts" / "system_prompt.md",
            Path(self.settings.paths.rulebook).name: self.settings.resolve_path(self.settings.paths.rulebook),
        }
        restored: list[str] = []
        for name, destination in mapping.items():
            source = backup / name
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                restored.append(str(destination))
        self.audit("ROLLBACK", "BACKUP_RESTORE", f"Restored backup {backup}", {"restored": restored})
        return {"backup": str(backup), "restored": restored}

    def latest_backup(self) -> Path | None:
        self.ensure_storage()
        backups = sorted([path for path in self.backup_dir.iterdir() if path.is_dir()], reverse=True)
        return backups[0] if backups else None

    def request_restart(self, reason: str, update_id: str | None = None) -> None:
        self.ensure_storage()
        self._write_json(self.restart_path, {"requested_at": _now_iso(), "reason": reason, "update_id": update_id})
        self.audit("RESTART_REQUESTED", reason, "Graceful restart requested at cycle boundary", {"update_id": update_id})

    def clear_restart_request(self) -> None:
        if self.restart_path.exists():
            self.restart_path.unlink()

    def record_successful_restart(self, reason: str, update_id: str | None = None) -> None:
        self.ensure_storage()
        payload = {
            "completed_at": _now_iso(),
            "reason": reason,
            "update_id": update_id,
            "code_version": detect_code_version(self.project_root),
        }
        self._write_json(self.last_restart_path, payload)
        self.audit("RESTARTED", reason, "Recorded successful live runner restart", payload)

    def deployment_state(self) -> dict[str, Any]:
        self.ensure_storage()
        latest_checkpoint = self.latest_checkpoint_file()
        return {
            "versions": self.current_versions(),
            "active_versions_file": _read_json(self.versions_path, {}),
            "pending_updates": self.pending_updates(),
            "last_successful_restart": _read_json(self.last_restart_path, {}),
            "active_checkpoint_timestamp": latest_checkpoint.get("written_at"),
            "latest_checkpoint": {
                "id": latest_checkpoint.get("checkpoint_id"),
                "cycle_number": latest_checkpoint.get("cycle_number"),
                "status": latest_checkpoint.get("status"),
            },
            "features": self.settings.features.model_dump(),
            "canary": self.settings.canary.model_dump(),
        }

    def audit(self, status: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": _now_iso(),
            "status": status,
            "type": event_type,
            "message": message,
            "payload": payload or {},
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str, sort_keys=True) + "\n")
        try:
            self.repository.save_health_check("update_manager", "PASS" if status not in {"FAILED", "VALIDATION_FAILED"} else "FAIL", False, message[:1000])
        except Exception:
            pass

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        tmp.replace(path)


def create_versioned_file(source: Path, destination_dir: Path, stem: str) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(destination_dir.glob(f"{stem}.v*.md"))
    next_number = len(existing) + 1
    target = destination_dir / f"{stem}.v{next_number:03d}.md"
    shutil.copy2(source, target)
    return target


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback
    except Exception:
        return fallback


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _settings_hash_or_empty(path: Path) -> str:
    try:
        return settings_hash(path)
    except Exception:
        return ""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.lower()).strip("-")[:80] or "backup"
