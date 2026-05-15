from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
from src.competition.workload import summarize_workload
from src.operations.preflight import has_critical_failures, run_preflight

app = typer.Typer(help="Crypto paper trading arena CLI.")


@app.command()
def init() -> None:
    """Initialize database, output files, and agent records."""
    settings = load_settings()
    setup_logging(settings.resolve_path(settings.paths.logs_dir))
    create_schema(settings.database_url)
    runner = CompetitionRunner(settings)
    synced_auth = _sync_openclaw_auth_from_env()
    if synced_auth:
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
        f"- Grok: {latest['grok_workload_pct']:.1f}%\n"
        f"- API cost this cycle: ${latest['api_cost_usd']:.6f}\n"
        f"- Tokens this cycle: DeepSeek {latest['deepseek_tokens']}, Grok {latest['grok_tokens']}"
    )


@app.command()
def dashboard(port: int = 8501) -> None:
    """Launch the Streamlit dashboard."""
    app_path = Path(__file__).resolve().parent / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port)], check=False)


def _sync_openclaw_auth_from_env() -> bool:
    """Write provider tokens from .env into the per-agent OpenClaw auth stores.

    This avoids interactive paste flows and keeps init usable in unattended
    setups. Existing profiles are replaced only for the two competition agents.
    """
    profiles = [
        ("crypto-deepseek", "deepseek", "deepseek:manual", os.getenv("DEEPSEEK_API_KEY")),
        ("crypto-grok", "xai", "xai:manual", os.getenv("XAI_API_KEY")),
    ]
    wrote_any = False
    for agent_id, provider, profile_id, token in profiles:
        if not token:
            continue
        agent_dir = Path.home() / ".openclaw" / "agents" / agent_id / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "profiles": {
                profile_id: {
                    "type": "token",
                    "provider": provider,
                    "token": token,
                }
            },
            "order": {provider: [profile_id]},
            "lastGood": {provider: profile_id},
        }
        state = {
            "version": 1,
            "order": {provider: [profile_id]},
            "lastGood": {provider: profile_id},
        }
        (agent_dir / "auth-profiles.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (agent_dir / "auth-state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        wrote_any = True
    return wrote_any


def _restart_openclaw_gateway() -> None:
    binary = os.getenv("OPENCLAW_BIN", "openclaw")
    subprocess.run([binary, "gateway", "restart"], check=False, capture_output=True, text=True)


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
