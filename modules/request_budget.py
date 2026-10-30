"""Explicit request-local fitting; never crop arbitrary user messages."""
from __future__ import annotations

import copy
import json
from typing import Callable


def size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False))


class BudgetedMessages(list):
    def __init__(self, messages, fitter: Callable[[int], list]):
        super().__init__(messages)
        self._fitter = fitter

    def fit(self, limit: int) -> list:
        if size(self) <= limit:
            return list(self)
        if limit < 2000:
            raise ValueError("No room for protected worker context")
        fitted = self._fitter(limit)
        if size(fitted) > limit:
            raise ValueError("Protected worker context exceeds request budget")
        return fitted


def review_messages(messages) -> BudgetedMessages:
    def fit(limit):
        original = json.loads(messages[1]["content"])
        command_limit = len(original.get("tool_evidence", ""))
        file_limit = 8000
        for _ in range(24):
            data = copy.deepcopy(original)
            text = data.get("tool_evidence", "")
            if len(text) > command_limit:
                data["tool_evidence"] = text[-command_limit:] if command_limit else ""
                data["tool_evidence_truncated"] = True
            changes = data.get("independent_git_changes", {})
            for row in changes.get("files", []):
                content = row.get("content", "")
                if len(content) > file_limit:
                    row["content"] = content[:file_limit]
                    row["truncated"] = True
                    changes["partial"] = True
            result = [dict(message) for message in messages]
            result[1]["content"] = json.dumps(data, ensure_ascii=False)
            if size(result) <= limit:
                return result
            if command_limit > 1000:
                command_limit //= 2
            elif file_limit > 128:
                file_limit //= 2
            else:
                break
        raise ValueError("Review task, report and change metadata cannot fit safely")
    return BudgetedMessages(messages, fit)
