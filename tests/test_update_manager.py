from __future__ import annotations

import yaml

from src.operations.update_manager import LiveUpdateManager


def _prepare_project_root(tmp_path, test_settings) -> None:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "settings.yaml").write_text(yaml.safe_dump(test_settings.model_dump(mode="json")), encoding="utf-8")
    (tmp_path / "prompts" / "system_prompt.md").write_text("system", encoding="utf-8")
    test_settings.resolve_path(test_settings.paths.rulebook).write_text("rules", encoding="utf-8")


def test_update_manager_queue_and_checkpoint_file(repository, test_settings, tmp_path) -> None:
    _prepare_project_root(tmp_path, test_settings)
    manager = LiveUpdateManager(test_settings, repository, project_root=tmp_path)
    update_id = manager.queue_update("CONFIG_RELOAD", {"reason": "test"})

    pending = manager.pending_updates()
    assert pending[0]["id"] == update_id
    assert pending[0]["type"] == "CONFIG_RELOAD"

    path = manager.write_checkpoint_file(
        {"open_positions": [], "memories": {}, "token_usage": {}},
        checkpoint_id=1,
        cycle_number=3,
        status="COMPLETED",
    )

    assert path.exists()
    latest = manager.latest_checkpoint_file()
    assert latest["cycle_number"] == 3
    assert latest["status"] == "COMPLETED"

    manager.mark_update(update_id, "APPLIED", {"ok": True})
    assert not manager.pending_updates()


def test_update_validation_reports_missing_checkpoint(repository, test_settings, tmp_path) -> None:
    _prepare_project_root(tmp_path, test_settings)

    manager = LiveUpdateManager(test_settings, repository, project_root=tmp_path)
    result = manager.validate_update(run_smoke=False)

    assert not result.passed
    assert result.checks["checkpoint"].startswith("FAIL")
