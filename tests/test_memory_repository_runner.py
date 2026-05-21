from __future__ import annotations

from src.agents.memory import AgentMemory
from src.agents.reflection import reflect_on_day, reflect_on_trade
from src.competition.runner import _parse_tool_request
from src.storage.models import TradeRecord
from src.storage.vector_store import LocalVectorStore


def test_repository_memory_and_reflection(repository, tmp_path) -> None:
    memory = AgentMemory(repository, LocalVectorStore(tmp_path / "vectors"))
    raw = "Daily review: equity=10000 realized_pnl=0. Keep valid setups only and preserve rule compliance."
    memory.save_lesson("crypto-deepseek", raw)
    lessons = memory.retrieve_lessons("crypto-deepseek", "range")
    assert "Trade only high-quality setups and maintain strict rule compliance." in lessons
    record = repository.lesson_records("crypto-deepseek", limit=1)[0]
    assert record.raw_text == raw
    assert record.summary == "Trade only high-quality setups and maintain strict rule compliance."

    trade = TradeRecord(
        id="t1",
        agent_id="crypto-deepseek",
        position_id="p1",
        action="CLOSE",
        direction="LONG",
        leverage=5,
        margin=100,
        notional=500,
        entry=100,
        exit_price=110,
        realized_pnl=50,
        notes="take_profit_2",
    )
    repository.add_trade(trade)
    lesson = reflect_on_trade(memory, trade)
    assert "win" in lesson
    count_before = len(repository.lessons("crypto-deepseek", limit=10))
    reflect_on_day(memory, "crypto-deepseek", 10050, 50, 0)
    # reflect_on_day intentionally does NOT write to lessons table (noise reduction)
    assert len(repository.lessons("crypto-deepseek", limit=10)) == count_before


def test_tool_request_parser() -> None:
    raw = '{"tool_requests":[{"tool":"get_indicators","arguments":{}}]}'
    parsed = _parse_tool_request(raw)
    assert parsed is not None
    assert parsed[0]["tool"] == "get_indicators"
    assert _parse_tool_request('{"decision":"NO_TRADE"}') is None
    assert _parse_tool_request("not json") is None
