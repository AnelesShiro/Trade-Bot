from __future__ import annotations


MODEL_PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek/deepseek-v4-flash": (0.14, 0.28),
    "qwen/qwen3-max-2026-01-23": (0.78, 3.90),
    "qwen3-max-2026-01-23": (0.78, 3.90),
}


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def estimate_cost_usd(model: str, prompt: str, response: str) -> tuple[int, int, float]:
    input_tokens = estimate_tokens(prompt)
    output_tokens = estimate_tokens(response)
    input_price, output_price = MODEL_PRICES_PER_MILLION.get(model, (0.0, 0.0))
    cost = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
    return input_tokens, output_tokens, cost
