"""Bounded run-wide observation memory, independent of dialogue trimming."""
import hashlib
import json
from collections import Counter


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class ProgressWatch:
    def __init__(self):
        self.seen = set()
        self.novel = 0
        self.repeated_windows = 0
        self.snapshot = None
        self.observed = 0
        self.new_diagnostics = 0
        self.repeated_tools = Counter()
        self.last_summary = {}

    def observe(self, tool, result):
        if tool in {"update_plan", "finish_task"}:
            return
        self.observed += 1
        # Requests, elapsed times and model paraphrases are not new evidence.
        fields = ("ok", "error", "path", "content", "files", "matches", "stdout",
                  "stderr", "exit_code", "changed", "truncated", "message")
        evidence = {k: result[k] for k in fields if k in result}
        digest = fingerprint(evidence)
        if digest not in self.seen:
            if result.get("ok", True) and result.get("exit_code", 0) in (0, None):
                self.novel += 1
            else:
                self.new_diagnostics += 1
            if len(self.seen) < 4096:
                self.seen.add(digest)
        else:
            label = tool + (" " + str(result["path"])[:250] if result.get("path") else "")
            if label in self.repeated_tools or len(self.repeated_tools) < 256:
                self.repeated_tools[label] += 1

    def checkpoint(self, snapshot):
        # Git evidence observes silent shell changes too. Partial or unavailable
        # evidence is labelled as such; yielding never asserts a clean checkout.
        state = fingerprint(snapshot)
        changed = state != self.snapshot
        self.snapshot = state
        # A rotating query or a fresh error must not renew a window dominated
        # by rereading known evidence. New source changes still reset it.
        repeat_heavy = self.novel * 2 <= self.observed
        if changed or not repeat_heavy:
            self.repeated_windows = 0
        else:
            self.repeated_windows += 1
        summary = {"new_observations": self.novel, "repository_evidence_changed": changed,
                   "observed_actions": self.observed, "new_diagnostics": self.new_diagnostics,
                   "repeated_or_failed_observations": self.observed - self.novel,
                   "repeated_windows": self.repeated_windows,
                   "repository_evidence_partial": snapshot.get("partial", not snapshot.get("available"))}
        self.last_summary = summary
        self.novel = 0
        self.observed = 0
        self.new_diagnostics = 0
        return self.repeated_windows >= 3, summary

    def diagnostics(self):
        return {"last_checkpoint": dict(self.last_summary),
                "actions_since_checkpoint": self.observed,
                "new_observations_since_checkpoint": self.novel,
                "most_repeated_tools": dict(self.repeated_tools.most_common(5))}
