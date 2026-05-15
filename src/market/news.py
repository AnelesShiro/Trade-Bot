from __future__ import annotations


def get_news_sentiment() -> float:
    """Return neutral sentiment until a news provider is configured.

    The runner does not invent news. Until a news provider is configured, the
    explicit sentiment is neutral and agents are told no external news feed was
    used.
    """
    return 0.0
