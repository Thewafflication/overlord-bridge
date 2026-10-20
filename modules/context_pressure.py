"""Validate recent context observations and avoid repeated threshold alerts."""

from datetime import datetime, timezone


def snapshot_for(brain):
    snapshot = getattr(brain, "context_snapshot", None)
    if not isinstance(snapshot, dict):
        return None
    if snapshot.get("session_id") != brain.session_id or snapshot.get("model") != brain.model:
        return None
    used, maximum = snapshot.get("used"), snapshot.get("maximum")
    if type(used) is not int or type(maximum) is not int or used < 0 or maximum <= 0:
        return None
    try:
        observed = datetime.fromisoformat(snapshot["observed_at"])
        age = (datetime.now(timezone.utc) - observed).total_seconds()
        if not 0 <= age <= 600:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return {**snapshot, "percentage": used / maximum * 100,
            "unit": snapshot.get("unit", "tokens"),
            "source": snapshot.get("source", "native usage snapshot")}


def describe(snapshot):
    return (f"{snapshot['used']:,}/{snapshot['maximum']:,} {snapshot['unit']} "
            f"({snapshot['percentage']:.1f}%) — {snapshot['source']}")


class ContextPolicy:
    def __init__(self, warn=75, compact=85, automatic=False):
        self.warn = max(1, min(99, warn))
        self.compact = max(self.warn, min(100, compact))
        self.automatic = automatic
        self._state = {}

    def action(self, brain, snapshot):
        key = (brain.name, brain.session_id, brain.model)
        warned, attempted = self._state.get(key, (False, False))
        percent = snapshot["percentage"]
        if percent < self.warn - 5:
            self._state[key] = (False, False)
            return None
        if self.automatic and percent >= self.compact and not attempted:
            self._state[key] = (True, True)
            return "compact"
        if percent >= self.warn and not warned:
            self._state[key] = (True, attempted)
            return "warn"
        return None
