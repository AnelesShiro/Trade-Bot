from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from src.config import PROJECT_ROOT, Settings, canonical_settings_payload, load_settings, settings_hash, settings_path
from src.storage.repository import ArenaRepository


class ConfigManager:
    def __init__(self, repository: ArenaRepository, config_path: str | Path | None = None) -> None:
        self.repository = repository
        self.path = settings_path(config_path)
        self.backup_dir = PROJECT_ROOT / "config" / "versions"
        self.code_version = detect_code_version(PROJECT_ROOT)
        self.config_hash = settings_hash(self.path)
        self.config_version_id = self.repository.save_config_version(
            self.config_hash,
            self.code_version,
            canonical_settings_payload(self.path),
            source="startup",
        )

    def reload_if_changed(self, current: Settings) -> Settings:
        changed = settings_hash(self.path)
        if changed == self.config_hash:
            return current
        return self.reload(source="auto-detect")

    def reload(self, source: str = "manual") -> Settings:
        settings = load_settings(self.path)
        self.code_version = detect_code_version(PROJECT_ROOT)
        self.config_hash = settings_hash(self.path)
        self.config_version_id = self.repository.save_config_version(
            self.config_hash,
            self.code_version,
            settings.model_dump(mode="json"),
            source=source,
        )
        self.repository.save_health_check("config", "PASS", False, f"Loaded config {self.config_hash[:12]} from {source}")
        return settings

    def rollback(self) -> Settings:
        versions = self.repository.config_versions(limit=2)
        if len(versions) < 2:
            raise RuntimeError("no previous configuration version found")
        previous = versions[1]
        payload = json.loads(previous.payload_json or "{}")
        self._backup_current()
        self.path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return self.reload(source=f"rollback:{previous.id}")

    def process_pending_commands(self, current: Settings) -> Settings:
        next_settings = current
        for command in self.repository.pending_control_commands():
            try:
                if command.command == "reload-config":
                    next_settings = self.reload(source=f"command:{command.id}")
                    self.repository.mark_control_command(command.id, "COMPLETED", {"config_hash": self.config_hash})
                elif command.command == "rollback-config":
                    next_settings = self.rollback()
                    self.repository.mark_control_command(command.id, "COMPLETED", {"config_hash": self.config_hash})
                else:
                    self.repository.mark_control_command(command.id, "FAILED", {"error": f"unknown command {command.command}"})
            except Exception as error:
                self.repository.mark_control_command(command.id, "FAILED", {"error": str(error)})
                self.repository.save_health_check("config", "FAIL", False, str(error))
        return next_settings

    def _backup_current(self) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = self.backup_dir / f"settings-{self.config_hash[:12]}.yaml"
        backup.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")


def detect_code_version(project_root: Path = PROJECT_ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return tree_fingerprint(project_root)


def tree_fingerprint(project_root: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted((project_root / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        stat = path.stat()
        hasher.update(str(path.relative_to(project_root)).encode("utf-8"))
        hasher.update(str(stat.st_mtime_ns).encode("utf-8"))
        hasher.update(str(stat.st_size).encode("utf-8"))
    return hasher.hexdigest()[:12]
