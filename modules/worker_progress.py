"""Bounded run-wide observation memory, independent of dialogue trimming."""
import hashlib
import json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class ProgressWatch:
    def __init__(self):
        self.seen = set()
        self.novel = 0
        self.repeated_windows = 0
        self.snapshot = None

    def observe(self, tool, result):
        if tool in {"update_plan", "finish_task"}:
            return
        # Requests, elapsed times and model paraphrases are not new evidence.
        fields = ("ok", "error", "path", "content", "files", "matches", "stdout",
                  "stderr", "exit_code", "changed", "truncated", "message")
        evidence = {k: result[k] for k in fields if k in result}
        digest = fingerprint(evidence)
        if digest not in self.seen:
            self.novel += 1
            if len(self.seen) < 4096:
                self.seen.add(digest)

    def checkpoint(self, snapshot):
        # Git evidence observes silent shell changes too. Partial or unavailable
        # evidence is labelled as such; yielding never asserts a clean checkout.
        state = fingerprint(snapshot)
        changed = state != self.snapshot
        self.snapshot = state
        if self.novel or changed:
            self.repeated_windows = 0
        else:
            self.repeated_windows += 1
        summary = {"new_observations": self.novel, "repository_evidence_changed": changed,
                   "repeated_windows": self.repeated_windows,
                   "repository_evidence_partial": snapshot.get("partial", not snapshot.get("available"))}
        self.novel = 0
        return self.repeated_windows >= 3, summary
