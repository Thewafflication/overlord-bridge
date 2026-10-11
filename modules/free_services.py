"""Fail-closed admission and per-request price ceiling for free cloud workers."""

from decimal import Decimal, InvalidOperation

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def validate_free_model(catalog: object, model: str) -> None:
    if not model.endswith(":free"):
        raise ValueError("OpenRouter worker requires an explicit :free model ID")
    if not isinstance(catalog, dict) or not isinstance(catalog.get("data"), list):
        raise ValueError("OpenRouter model catalog is invalid")
    matches = [m for m in catalog["data"] if isinstance(m, dict) and m.get("id") == model]
    if len(matches) != 1:
        raise ValueError("Free model is missing or ambiguous in the current catalog")
    entry = matches[0]
    prices = entry.get("pricing")
    if not isinstance(prices, dict):
        raise ValueError("Free model pricing is unavailable")
    for field in ("prompt", "completion"):
        try:
            price = Decimal(str(prices[field]))
        except (KeyError, InvalidOperation, ValueError):
            raise ValueError("Free model pricing is invalid") from None
        if not price.is_finite() or price != 0:
            raise ValueError("Free model must have zero input and output prices")
    supported = entry.get("supported_parameters")
    # A bare string would make `"tools" in supported` a substring test.
    if not isinstance(supported, list) or "tools" not in supported:
        raise ValueError("Free worker model must advertise tool support")


def free_provider_policy() -> dict:
    # Enforced on every turn, including turns after tool execution.
    return {"allow_fallbacks": False, "require_parameters": True,
            "max_price": {"prompt": 0, "completion": 0}}
