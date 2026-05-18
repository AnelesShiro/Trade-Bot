from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import typer

from src.cloud.git_sync import sync_dashboard_snapshot
from src.cloud.snapshot_exporter import write_dashboard_snapshot
from src.competition.config_manager import ConfigManager
from src.competition.runner import CompetitionRunner
from src.config import load_settings
from src.logger import setup_logging
from src.storage.models import build_session_factory, create_schema
from src.storage.repository import ArenaRepository
from src.agents.shared_learning import SharedLearningManager
from src.competition.api_cost_audit import summarize_api_costs
from src.competition.workload import summarize_workload
from src.operations.preflight import has_critical_failures, run_preflight
from src.operations.update_manager import LiveUpdateManager, create_versioned_file

app = typer.Typer(help="Crypto paper trading arena CLI.")


@app.command()
def init() -> None:
    """Initialize database, output files, and agent records."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    create_schema(settings.database_url)
    runner = CompetitionRunner(settings)
    _sync_openclaw_agent_registry(settings)
    synced_base_urls = _sync_openclaw_provider_base_urls(settings)
    synced_auth = _sync_openclaw_auth_from_env(settings)
    if synced_auth or synced_base_urls:
        _restart_openclaw_gateway()
    for relative in [settings.paths.signals, settings.paths.ledger, settings.paths.evaluation]:
        path = settings.resolve_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
    typer.echo(f"Initialized {settings.competition.name}")


@app.command("run-once")
def run_once() -> None:
    """Run one competition decision cycle."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    CompetitionRunner(settings).run_once()
    typer.echo("Completed one arena cycle.")


@app.command("run-live")
def run_live(resume: bool = typer.Option(False, "--resume", help="Resume from the latest crash-safe checkpoint.")) -> None:
    """Run the scheduled live loop forever."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    CompetitionRunner(settings).run_live(resume=resume)


@app.command("export-snapshot")
def export_snapshot() -> None:
    """Export the compact cloud dashboard snapshot."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    path = write_dashboard_snapshot(settings, repository)
    typer.echo(f"Exported dashboard snapshot: {path}")


@app.command("sync-github")
def sync_github(skip_render: bool = typer.Option(False, "--skip-render", help="Commit with [skip render].")) -> None:
    """Commit and push the dashboard snapshot to GitHub when it changed."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    result = sync_dashboard_snapshot(settings, repository, skip_render=skip_render)
    typer.echo(json.dumps(result.__dict__, indent=2))
    if result.attempted and result.changed and not result.pushed:
        raise typer.Exit(code=1)


@app.command("cloud-update")
def cloud_update(skip_render: bool = typer.Option(False, "--skip-render", help="Commit with [skip render].")) -> None:
    """Export the dashboard snapshot, commit it, and push to GitHub."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    path = write_dashboard_snapshot(settings, repository)
    result = sync_dashboard_snapshot(settings, repository, skip_render=skip_render)
    typer.echo(f"Snapshot: {path}")
    typer.echo(json.dumps(result.__dict__, indent=2))
    if result.attempted and result.changed and not result.pushed:
        raise typer.Exit(code=1)


@app.command("deploy-check")
def deploy_check() -> None:
    """Check local readiness for GitHub and Render dashboard deployment."""
    settings = load_settings()
    create_schema(settings.database_url)
    checks = []
    snapshot_path = settings.resolve_path(settings.cloud_dashboard.snapshot_path)
    checks.append(("snapshot", snapshot_path.exists(), str(snapshot_path)))
    checks.append(("render.yaml", (Path.cwd() / "render.yaml").exists(), "Render service definition"))
    checks.append(("Procfile", (Path.cwd() / "Procfile").exists(), "optional process file"))
    git_root = _git_output(["rev-parse", "--show-toplevel"])
    checks.append(("git repository", bool(git_root), git_root or "not a git repository"))
    remote = _git_output(["remote", "get-url", "origin"])
    checks.append(("git origin", bool(remote), remote or "origin remote is not configured"))
    branch = _git_output(["branch", "--show-current"])
    checks.append(("git branch", branch == settings.cloud_dashboard.git_branch, branch or "unknown"))
    checks.append((".env gitignored", _is_gitignored(".env"), ".env should never be committed"))
    failed = False
    for name, passed, detail in checks:
        marker = "PASS" if passed else "FAIL"
        typer.echo(f"{marker} {name} - {detail}")
        failed = failed or not passed
    if failed:
        raise typer.Exit(code=1)


@app.command("reload-config")
def reload_config() -> None:
    """Queue a hot config reload for a running arena, or validate and record it now."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = ConfigManager(repository)
    reloaded = manager.reload(source="cli")
    command_id = repository.queue_control_command("reload-config")
    typer.echo(
        f"Reloaded config {manager.config_hash[:12]} locally and queued command {command_id} "
        f"for live runners. Agents: {', '.join(agent.id for agent in reloaded.agents)}"
    )


@app.command("rollback-config")
def rollback_config() -> None:
    """Restore the previous recorded configuration version and queue live rollback."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = ConfigManager(repository)
    rolled_back = manager.rollback()
    command_id = repository.queue_control_command("reload-config", {"reason": "rollback already applied by CLI"})
    typer.echo(
        f"Rolled back to config {manager.config_hash[:12]} and queued command {command_id}. "
        f"Agents: {', '.join(agent.id for agent in rolled_back.agents)}"
    )


@app.command("queue-prompt-update")
def queue_prompt_update(
    source: Path = typer.Argument(..., help="Path to the new system prompt markdown file."),
    agent: list[str] | None = typer.Option(None, "--agent", help="Optional canary target agent id."),
) -> None:
    """Queue a versioned prompt update for the next cycle boundary."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = LiveUpdateManager(settings, repository)
    source_path = source if source.is_absolute() else Path.cwd() / source
    version = create_versioned_file(source_path, Path.cwd() / "prompts", "system_prompt")
    update_id = manager.queue_update("PROMPT_UPDATE", {"version_path": str(version), "target_agents": agent or []})
    typer.echo(f"Queued prompt update {update_id}: {version}")


@app.command("queue-rulebook-update")
def queue_rulebook_update(source: Path = typer.Argument(..., help="Path to the new rulebook markdown file.")) -> None:
    """Queue a versioned rulebook update for the next cycle boundary."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = LiveUpdateManager(settings, repository)
    source_path = source if source.is_absolute() else Path.cwd() / source
    version = create_versioned_file(source_path, Path.cwd() / "rulebooks", "rulebook")
    update_id = manager.queue_update("RULEBOOK_UPDATE", {"version_path": str(version)})
    typer.echo(f"Queued rulebook update {update_id}: {version}")


@app.command("safe-restart")
def safe_restart(wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for the boundary update to apply, then start run-live --resume.")) -> None:
    """Request a cycle-boundary restart and resume from the latest checkpoint."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = LiveUpdateManager(settings, repository)
    update_id = manager.queue_update("CODE_RESTART", {})
    typer.echo(f"Queued safe restart {update_id}. It will apply after the current cycle checkpoint.")
    if not wait:
        _start_restart_watcher(update_id)
        typer.echo("Started detached restart watcher; live runner will resume after the boundary restart applies.")
        return
    _wait_for_restart_and_resume(manager, update_id)


@app.command("watch-safe-restart")
def watch_safe_restart(update_id: str = typer.Argument(...), timeout_seconds: int = typer.Option(1800, "--timeout-seconds")) -> None:
    """Wait for an existing safe restart update to apply, then resume live runner."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = LiveUpdateManager(settings, repository)
    _wait_for_restart_and_resume(manager, update_id, timeout_seconds=timeout_seconds)


def _wait_for_restart_and_resume(manager: LiveUpdateManager, update_id: str, timeout_seconds: int = 1800) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        matching = [entry for entry in manager.read_queue() if entry.get("id") == update_id]
        status = matching[0].get("status") if matching else "UNKNOWN"
        if status == "APPLIED":
            for _ in range(24):
                if not _live_runner_pids():
                    break
                time.sleep(2)
            _start_live_detached()
            manager.clear_restart_request()
            manager.record_successful_restart("CODE_RESTART", update_id)
            typer.echo("Restarted live runner with --resume.")
            return
        if status == "FAILED":
            raise typer.Exit(code=1)
        time.sleep(5)
    typer.echo("Timed out waiting for safe restart boundary.")
    raise typer.Exit(code=1)


def _start_restart_watcher(update_id: str) -> None:
    logs = Path.cwd() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout = (logs / "safe-restart-watch.out.log").open("ab")
    stderr = (logs / "safe-restart-watch.err.log").open("ab")
    kwargs: dict[str, Any] = {
        "cwd": Path.cwd(),
        "stdout": stdout,
        "stderr": stderr,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen([sys.executable, "-m", "src.cli", "watch-safe-restart", update_id], **kwargs)

@app.command("rollback")
def rollback(to: str = typer.Option("previous", "--to", help="Rollback target. Use 'previous' for latest backup or provide a backup path.")) -> None:
    """Queue rollback at the next cycle boundary, then restart with resume."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = LiveUpdateManager(settings, repository)
    backup_path = None if to == "previous" else to
    update_id = manager.queue_update("ROLLBACK", {"backup_path": backup_path})
    typer.echo(f"Queued rollback {update_id}. It will apply after the current cycle checkpoint.")


@app.command("show-versions")
def show_versions() -> None:
    """Show active code/config/prompt/rulebook versions and pending updates."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = LiveUpdateManager(settings, repository)
    typer.echo(json.dumps(manager.deployment_state(), indent=2, default=str))


@app.command("validate-update")
def validate_update(smoke: bool = typer.Option(True, "--smoke/--no-smoke", help="Run compile smoke checks.")) -> None:
    """Validate config, prompts, rulebook, checkpoint, and smoke checks before an update."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = LiveUpdateManager(settings, repository)
    result = manager.validate_update(run_smoke=smoke)
    typer.echo(json.dumps({"passed": result.passed, "checks": result.checks}, indent=2))
    if not result.passed:
        raise typer.Exit(code=1)


@app.command()
def backtest() -> None:
    """Run a lightweight backtest diagnostic cycle.

    The current implementation fetches historical market data and records the
    same diagnostic tools used in live mode. It does not call agents.
    """
    from src.tools.get_market_state import get_market_state
    from src.tools.backtest_pattern import backtest_pattern

    settings = load_settings()
    market_state = get_market_state(settings)
    import pandas as pd

    frame = pd.DataFrame([c.model_dump() for c in market_state.candles])
    typer.echo(backtest_pattern(frame))


@app.command()
def evaluate() -> None:
    """Recompute and write the leaderboard."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    from src.competition.runner import CompetitionRunner
    from src.tools.get_market_state import get_market_state

    runner = CompetitionRunner(settings)
    runner._write_outputs(get_market_state(settings))
    typer.echo(f"Wrote {settings.paths.evaluation}")


@app.command("promote-lessons")
def promote_lessons() -> None:
    """Promote qualified private lessons into the shared knowledge base."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = SharedLearningManager(repository, settings)
    manager.ensure_storage()
    result = manager.promote_lessons()
    typer.echo(json.dumps(result, indent=2))


@app.command("analyze-diversity")
def analyze_diversity() -> None:
    """Analyze recent agent similarity and save diversity metrics."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = SharedLearningManager(repository, settings)
    manager.ensure_storage()
    result = manager.analyze_diversity()
    typer.echo(json.dumps(result, indent=2))


@app.command("rebuild-shared-knowledge")
def rebuild_shared_knowledge() -> None:
    """Rebuild shared lesson candidates from private lesson history."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    manager = SharedLearningManager(repository, settings)
    manager.ensure_storage()
    result = manager.rebuild_shared_knowledge()
    typer.echo(json.dumps(result, indent=2))


@app.command("preflight-check")
def preflight_check() -> None:
    """Verify critical production readiness before live execution."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    results = run_preflight(settings)
    for result in results:
        repository.save_health_check(result.component, result.status, result.critical, result.message)
        marker = "PASS" if result.passed else "FAIL"
        critical = "critical" if result.critical else "non-critical"
        typer.echo(f"{marker} {result.component} ({critical}) - {result.message}")
    if has_critical_failures(results):
        raise typer.Exit(code=1)


@app.command("analyze-workload")
def analyze_workload(limit: int = 50) -> None:
    """Summarize workload attribution from recorded competition cycles."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    typer.echo(json.dumps(summarize_workload(repository, limit=limit), indent=2))


@app.command("workload-report")
def workload_report(limit: int = 50) -> None:
    """Print a human-readable local vs AI workload report."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    summary = summarize_workload(repository, limit=limit)
    latest = summary.get("latest")
    if not latest:
        typer.echo("No workload cycles recorded yet. Run a competition cycle first.")
        return
    typer.echo(
        "Workload Attribution\n"
        f"- Local Machine: {latest['local_workload_pct']:.1f}%\n"
        f"- DeepSeek: {latest['deepseek_workload_pct']:.1f}%\n"
        f"- Challenger: {latest['grok_workload_pct']:.1f}%\n"
        f"- API cost this cycle: ${latest['api_cost_usd']:.6f}\n"
        f"- Tokens this cycle: DeepSeek {latest['deepseek_tokens']}, Challenger {latest['grok_tokens']}"
    )


@app.command("audit-api-costs")
def audit_api_costs(limit: int = 1000) -> None:
    """Print the raw API request cost audit summary."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    typer.echo(json.dumps(summarize_api_costs(repository, limit=limit), indent=2, default=str))


@app.command("analyze-grok-spike")
def analyze_grok_spike(limit: int = 1000) -> None:
    """Diagnose legacy Grok/Qwen challenger API cost anomalies from audit rows."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    summary = summarize_api_costs(repository, limit=limit)
    typer.echo("Challenger Cost Spike Diagnosis")
    for finding in summary.get("diagnosis", []):
        typer.echo(f"- {finding}")
    rows = {
        key: value
        for key, value in (summary.get("by_agent") or {}).items()
        if "grok" in key.lower() or "qwen" in key.lower()
    }
    if rows:
        typer.echo(json.dumps(rows, indent=2, default=str))


@app.command("analyze-qwen-spike")
def analyze_qwen_spike(limit: int = 1000) -> None:
    """Diagnose Qwen challenger API cost anomalies from recorded request-level audit rows."""
    analyze_grok_spike(limit=limit)


@app.command("compare-agent-costs")
def compare_agent_costs(limit: int = 1000) -> None:
    """Compare active agent request counts, tokens, retries, and cost."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    summary = summarize_api_costs(repository, limit=limit)
    rows = summary.get("by_agent") or {}
    if not rows:
        typer.echo("No API request audit rows recorded yet.")
        return
    typer.echo("| Agent | Requests | Avg prompt tokens | Avg completion tokens | Avg cost | Max request cost | Retries | Prompt growth |")
    typer.echo("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for agent_id, row in rows.items():
        typer.echo(
            f"| {agent_id} | {int(row['request_count'])} | "
            f"{float(row['average_prompt_tokens']):.1f} | {float(row['average_completion_tokens']):.1f} | "
            f"${float(row['average_total_cost_usd']):.6f} | ${float(row['max_single_request_cost_usd']):.6f} | "
            f"{int(row['retry_count'])} | {float(row['prompt_growth_ratio']):.2f}x |"
        )


@app.command("list-pending-orders")
def list_pending_orders(agent: str | None = None) -> None:
    """List active pending conditional orders."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    rows = repository.list_pending_orders(status="PENDING", agent_id=agent)
    if not rows:
        typer.echo("No pending orders.")
        return
    typer.echo(json.dumps([{"id": row.id, "agent_id": row.agent_id, "expires_at": str(row.expires_at)} for row in rows], indent=2))


@app.command("cancel-pending-order")
def cancel_pending_order(order_id: str = typer.Option(..., "--id")) -> None:
    """Cancel a pending conditional order."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    if repository.cancel_pending_order(order_id):
        typer.echo(f"Cancelled {order_id}")
    else:
        raise typer.Exit(code=1)


@app.command("list-cooldowns")
def list_cooldowns() -> None:
    """List active agent entry cooldowns."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    rows = repository.list_cooldowns(active_only=True)
    typer.echo(json.dumps([{"agent_id": row.agent_id, "reason": row.reason, "ends_at": str(row.ends_at)} for row in rows], indent=2))


@app.command("clear-cooldown")
def clear_cooldown(agent: str = typer.Option(..., "--agent")) -> None:
    """Clear an active entry cooldown for an agent."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    if repository.clear_cooldown(agent):
        typer.echo(f"Cleared cooldown for {agent}")
    else:
        raise typer.Exit(code=1)


@app.command("show-failover-status")
def show_failover_status() -> None:
    """Show active API failover routes per agent."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    from src.agents.api_failover import ApiFailoverManager

    manager = ApiFailoverManager(settings, repository)
    payload = {}
    for agent in settings.agents:
        route = manager.active_route(agent)
        payload[agent.id] = {
            "using_fallback": route.using_fallback,
            "provider": route.provider,
            "model": route.model,
            "fallback_index": route.fallback_index,
        }
    typer.echo(json.dumps(payload, indent=2))


@app.command("list-risk-notifications")
def list_risk_notifications(limit: int = typer.Option(50, "--limit")) -> None:
    """List recent risk automation notifications."""
    settings = load_settings()
    create_schema(settings.database_url)
    repository = ArenaRepository(build_session_factory(settings.database_url))
    rows = repository.risk_notifications(limit=limit)
    payload = [
        {
            "created_at": str(row.created_at),
            "agent_id": row.agent_id,
            "event_type": row.event_type,
            "severity": row.severity,
            "message": row.message,
        }
        for row in rows
    ]
    typer.echo(json.dumps(payload, indent=2))


@app.command()
def dashboard(port: int = 8501) -> None:
    """Launch the Streamlit dashboard."""
    app_path = Path(__file__).resolve().parent / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port)], check=False)


def _sync_openclaw_auth_from_env(settings) -> bool:
    """Write provider tokens from .env into the per-agent OpenClaw auth stores.

    This avoids interactive paste flows and keeps init usable in unattended
    setups. Existing profiles are replaced only for the two competition agents.
    """
    profiles_by_agent: dict[str, dict[str, tuple[str, str]]] = {}
    for agent in settings.agents:
        provider = agent.provider
        key_name = agent.llm.LLM_API_KEY
        if key_name and os.getenv(key_name):
            profiles_by_agent.setdefault(agent.id, {})[provider] = (f"{provider}:manual", os.getenv(key_name) or "")
        for route in agent.api_failover.fallback_chain:
            if route.LLM_API_KEY and os.getenv(route.LLM_API_KEY):
                profiles_by_agent.setdefault(agent.id, {})[route.provider] = (
                    f"{route.provider}:failover",
                    os.getenv(route.LLM_API_KEY) or "",
                )
    wrote_any = False
    for agent_id, provider_profiles in profiles_by_agent.items():
        if not provider_profiles:
            continue
        agent_dir = Path.home() / ".openclaw" / "agents" / agent_id / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        profiles_payload = {}
        order_payload = {}
        last_good_payload = {}
        for provider, (profile_id, token) in provider_profiles.items():
            profiles_payload[profile_id] = {
                "type": "token",
                "provider": provider,
                "token": token,
            }
            order_payload[provider] = [profile_id]
            last_good_payload[provider] = profile_id
        payload = {
            "version": 1,
            "profiles": profiles_payload,
            "order": order_payload,
            "lastGood": last_good_payload,
        }
        state = {
            "version": 1,
            "order": order_payload,
            "lastGood": last_good_payload,
        }
        (agent_dir / "auth-profiles.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (agent_dir / "auth-state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        wrote_any = True
    return wrote_any


def _sync_openclaw_provider_base_urls(settings) -> bool:
    """Sync configured provider base URLs into OpenClaw's provider config.

    OpenClaw's agent registry stores the locked provider/model route, while
    custom endpoints such as Qwen Standard Global live under models.providers.
    """
    provider_updates: dict[str, dict[str, Any]] = {}
    for agent in settings.agents:
        routes = [(agent.llm.LLM_PROVIDER, agent.llm.LLM_MODEL, agent.llm.LLM_BASE_URL)]
        routes.extend((route.provider, route.model, route.LLM_BASE_URL) for route in agent.api_failover.fallback_chain)
        for provider_raw, model_raw, base_url_raw in routes:
            base_url = str(base_url_raw or "").strip()
            if not base_url:
                continue
            provider = str(provider_raw or "").strip()
            model = str(model_raw or "").strip()
            if not provider or not model:
                continue
            provider_updates[provider] = {
                "baseUrl": base_url,
                "api": "openai-completions",
                "models": [{"id": model, "name": model}],
            }
    if not provider_updates:
        return False

    config_path = Path.home() / ".openclaw" / "openclaw.json"
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
    else:
        payload = {}

    models = payload.setdefault("models", {})
    models["mode"] = "merge"
    providers = models.setdefault("providers", {})
    changed = False
    for provider, update in provider_updates.items():
        current = providers.get(provider)
        if current != update:
            providers[provider] = update
            changed = True
    if not changed:
        return False

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True


def _sync_openclaw_agent_registry(settings) -> None:
    """Ensure OpenClaw knows every configured competition agent.

    The Gateway rejects per-request model overrides for this caller, so the
    OpenClaw agent registry must carry the locked model id before live runs.
    """
    binary = os.getenv("OPENCLAW_BIN", "openclaw")
    existing = subprocess.run([binary, "agents", "list"], capture_output=True, text=True, check=False)
    listed = existing.stdout or ""
    for agent in settings.agents:
        if f"- {agent.id}" in listed:
            continue
        openclaw_model = agent.model if "/" in agent.model else f"{agent.provider}/{agent.model}"
        subprocess.run(
            [
                binary,
                "agents",
                "add",
                agent.id,
                "--model",
                openclaw_model,
                "--workspace",
                str(Path.home() / ".openclaw" / "workspaces" / agent.id),
                "--agent-dir",
                str(Path.home() / ".openclaw" / "agents" / agent.id / "agent"),
                "--non-interactive",
            ],
            check=False,
            capture_output=True,
            text=True,
        )


def _restart_openclaw_gateway() -> None:
    binary = os.getenv("OPENCLAW_BIN", "openclaw")
    subprocess.run([binary, "gateway", "restart"], check=False, capture_output=True, text=True)


def _start_live_detached() -> None:
    logs = Path.cwd() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout = (logs / "safe-restart.out.log").open("ab")
    stderr = (logs / "safe-restart.err.log").open("ab")
    kwargs: dict[str, Any] = {
        "cwd": Path.cwd(),
        "stdout": stdout,
        "stderr": stderr,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen([sys.executable, "-m", "src.cli", "run-live", "--resume"], **kwargs)


def _live_runner_pids() -> list[int]:
    if os.name == "nt":
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -like '*src.cli run-live*' -and $_.Name -like 'python*' } | "
                "Select-Object -ExpandProperty ProcessId",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]
    result = subprocess.run(["pgrep", "-f", "src.cli run-live"], capture_output=True, text=True, check=False)
    current = os.getpid()
    return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit() and int(line) != current]


def _git_output(args: list[str]) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=Path.cwd(), capture_output=True, text=True, check=False)
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _is_gitignored(path: str) -> bool:
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=Path.cwd(), capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return True
    gitignore = Path.cwd() / ".gitignore"
    if not gitignore.exists():
        return False
    return path in {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}


if __name__ == "__main__":
    app()
