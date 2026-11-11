"""Owner-defined project tasks and harness-run acceptance checks."""
from __future__ import annotations

import json
import hashlib
import os
import re
from pathlib import Path, PureWindowsPath

from modules.command_activity import redact_text


def load_task(path: Path | None, folder: Path) -> dict | None:
    if path is None or not path.exists():
        return None
    if path.stat().st_size > 128_000:
        raise ValueError("Project task queue exceeds 128 KB")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("tasks"), list):
        raise ValueError("Invalid project task queue")
    configured = False
    for task in data["tasks"]:
        if not isinstance(task, dict) or not isinstance(task.get("folder"), str):
            raise ValueError("Invalid project task entry")
        if Path(task["folder"]).resolve() != folder.resolve():
            continue
        configured = True
        if task.get("state") != "ready":
            continue
        if not all(isinstance(task.get(key), str) and task[key].strip() for key in ("id", "requirement", "task")):
            raise ValueError("Project task needs an ID, requirement and deliverable")
        checks = task.get("checks")
        if not isinstance(checks, list) or not 1 <= len(checks) <= 12:
            raise ValueError("Project task needs between one and twelve acceptance checks")
        for check in checks:
            if (not isinstance(check, dict) or check.get("tool") not in {"run_command", "run_python"}
                    or not isinstance(check.get("arguments"), dict)
                    or not isinstance(check.get("name"), str) or not check["name"].strip()):
                raise ValueError("Invalid acceptance check")
        publication = task.get("publication")
        protected = task.get('protected_files', {})
        if (not isinstance(protected, dict) or len(protected) > 100
                or not all(isinstance(p, str) and p and not Path(p).anchor and not PureWindowsPath(p).anchor
                           and '..' not in re.split(r'[\\/]', p)
                           and isinstance(h, str) and re.fullmatch(r'[0-9a-f]{64}', h)
                           for p, h in protected.items())):
            raise ValueError('Invalid protected owner files')
        if publication is not None:
            if (not isinstance(publication, dict) or set(publication) != {"remote", "branch", "paths"}
                    or not all(isinstance(publication[k], str) and re.fullmatch(r"[\w./-]+", publication[k])
                               and not publication[k].startswith("-") for k in ("remote", "branch"))
                    or not isinstance(publication["paths"], list) or not publication["paths"]
                    or not all(isinstance(p, str) and p and not Path(p).is_absolute()
                               and ".." not in Path(p).parts for p in publication["paths"])):
                raise ValueError("Invalid publication requirement")
        return task
    return {"state": "idle"} if configured else None


def protected_paths(task, allowed):
    """Resolve explicit owner files without following links or reading secrets."""
    root = Path(task['folder']).resolve()
    paths = []
    for name in task.get('protected_files', {}):
        path = root / name
        if not path.is_relative_to(root) or not allowed(path):
            raise ValueError('Protected owner path is not allowed')
        for part in (path, *path.parents):
            if part == root:
                break
            if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
                raise ValueError('Protected owner path traverses a link')
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError('Protected owner file unavailable or exceeds 2MB')
        paths.append(path)
    return paths


def protected_file_failures(task, paths):
    """Call after acquiring read-only handles so the checked bytes stay pinned."""
    failures = []
    for (name, expected), path in zip(task.get('protected_files', {}).items(), paths, strict=True):
        with path.open('rb') as stream:
            data = stream.read(2_000_001)
        actual = hashlib.sha256(data).hexdigest()
        if len(data) > 2_000_000 or actual != expected:
            failures.append({'path': name, 'expected_sha256': expected, 'actual_sha256': actual})
    return failures


def is_git_push(tool: str, arguments: dict) -> bool:
    # Mechanical shell command recognition, not natural-language intent routing.
    command = arguments.get("command", "")
    return tool == "run_command" and isinstance(command, str) and bool(re.search(
        r'(?i)(?:^|[\s;&|])git(?:\.exe)?\s+push(?:\s|$)', command))


def complete_task(path: Path, snapshot: dict) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for task in data["tasks"]:
        if task == snapshot:
            task["state"] = "completed"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, path)
            return
    raise ValueError("Project task changed during execution; completion needs review")


async def validate(task: dict, execute, *, completion: bool = False) -> dict:
    """Run configured checks, in order, independently of worker claims."""
    results = []
    checks = list(task["checks"])
    if completion and task.get("publication"):
        publication = task["publication"]
        code = (
            "import subprocess\n"
            f"subprocess.run(['git','diff','--exit-code','HEAD','--',*{publication['paths']!r}],check=True)\n"
            "head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()\n"
            f"remote=subprocess.check_output(['git','ls-remote','--exit-code',{publication['remote']!r},"
            f"{'refs/heads/' + publication['branch']!r}],text=True).split()\n"
            "assert remote and remote[0] == head, 'Remote branch does not match validated HEAD'\n"
            "print('Validated paths committed and remote HEAD confirmed')"
        )
        checks.append({"name": "Owned paths committed and remote SHA verified",
                       "tool": "run_python", "arguments": {"code": code}})
    for check in checks:
        result = await execute(check["tool"], check["arguments"])
        passed = (result.get("ok") is True and type(result.get("exit_code")) is int
                  and result["exit_code"] == 0 and not result.get("timed_out"))
        recorded = {key: redact_text(value)[-4000:] if isinstance(value, str) else value
                    for key, value in result.items() if key in {
                        "ok", "exit_code", "error", "timed_out", "stdout", "stderr"}}
        results.append({"name": check["name"], "passed": passed, "result": recorded})
        if not passed:
            break
    return {"task_id": task["id"], "passed": len(results) == len(checks)
            and all(row["passed"] for row in results), "checks": results}
