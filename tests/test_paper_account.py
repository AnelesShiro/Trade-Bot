from src.storage.models import create_schema, build_session_factory
from src.storage.repository import ArenaRepository
from src.trading.paper_account import PaperAccount


def test_empty_account_summary(tmp_path) -> None:
    db = tmp_path / "arena.db"
    url = f"sqlite:///{db}"
    create_schema(url)
    repo = ArenaRepository(build_session_factory(url))
    account = PaperAccount("agent", 10000, repo)
    summary = account.summary(100000)
    assert summary.equity == 10000
    assert summary.open_positions == []
