"""Conservative mechanical allowlist for routine commands in a workspace.

Build/test recipes execute project code. This policy trusts that code; it does
not treat an executable name as proof that every invocation is harmless.
"""

from pathlib import Path, PureWindowsPath
import os
import re
import sys


def _known_shell_path(executable: str) -> bool:
    if sys.platform == "win32":
        windows = PureWindowsPath(os.environ.get("SystemRoot", "C:/Windows"))
        programs = PureWindowsPath(os.environ.get("ProgramFiles", "C:/Program Files"))
        known = {windows / "System32/cmd.exe",
                 windows / "System32/WindowsPowerShell/v1.0/powershell.exe",
                 programs / "PowerShell/7/pwsh.exe"}
        return PureWindowsPath(executable) in known
    return executable in {"/bin/bash", "/usr/bin/bash", "/bin/sh", "/usr/bin/sh"}


def _tokens(command):
    if isinstance(command, list):
        if not command or not all(isinstance(token, str) for token in command):
            return None
        exe = command[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        wrappers = {"bash": {"-c", "-lc"}, "sh": {"-c"},
                    "cmd.exe": {"/c"}, "cmd": {"/c"},
                    "powershell.exe": {"-command"}, "powershell": {"-command"},
                    "pwsh.exe": {"-command"}, "pwsh": {"-command"}}
        if exe in wrappers:
            if exe != command[0].lower() and not _known_shell_path(command[0]):
                return None
            args = [arg.lower() for arg in command[1:-1]]
            if (args and args[-1] in wrappers[exe]
                    and all(arg in {"-noprofile", "-noninteractive", "-nologo"} for arg in args[:-1])):
                return _tokens(command[-1])
            return None
        # Never trust a path-qualified executable or shell-escaped argv.
        if exe != command[0].lower():
            return None
        if any(not re.fullmatch(r"[A-Za-z0-9_./=:@+,-]+", token) for token in command):
            return None
        return command
    if not isinstance(command, str) or not command.strip():
        return None
    # Fail closed on quoting, redirection, chaining, expansion and substitutions.
    if not re.fullmatch(r"[A-Za-z0-9_./=:@+, \t-]+", command):
        return None
    return command.split()


def is_safe_command(command, workspace: str, cwd: str | None = None) -> bool:
    tokens = _tokens(command)
    if not tokens or not workspace:
        return False
    try:
        root = Path(workspace).resolve()
        actual = Path(cwd).resolve() if cwd else root
        if not root.is_dir() or not actual.is_dir() or not actual.is_relative_to(root):
            return False
    except (OSError, ValueError, TypeError, RuntimeError):
        return False
    for token in tokens[1:]:
        value = token.split("=", 1)[-1]
        if (value.startswith(("/", "~")) or ":" in value or ".." in value.split("/")
                or ".env" in value.lower()
                or value.lower().endswith((".log", ".mp4", ".mkv"))):
            return False
        # Relative filesystem arguments must stay inside the workspace even
        # through symlinks. Flags and numeric arguments are not paths.
        if not value.startswith("-"):
            try:
                if not (actual / value).resolve().is_relative_to(root):
                    return False
            except (OSError, ValueError, RuntimeError):
                return False
    exe = tokens[0].lower().removesuffix(".exe")
    args = tokens[1:]
    if exe == "git":
        if not args:
            return False
        sub, rest = args[0], args[1:]
        if sub == "branch":
            return bool(rest) and all(arg in {"--list", "-a", "-r", "--show-current"} for arg in rest)
        if sub not in {"status", "diff", "log", "show", "ls-files", "rev-parse", "ls-tree"}:
            return False
        flags = {"--", "-s", "--short", "--porcelain", "--branch", "--stat", "--name-only",
                 "--name-status", "--cached", "--staged", "--check", "--no-ext-diff",
                 "--no-textconv", "--oneline", "--graph", "--all", "--decorate", "-p",
                 "--abbrev-ref", "--show-toplevel", "--show-prefix", "--is-inside-work-tree",
                 "--verify", "--quiet", "-q", "-r", "--full-tree", "-n"}
        return all(not arg.startswith("-") or arg in flags
                   or re.fullmatch(r"-(?:n)?[0-9]+", arg)
                   or re.fullmatch(r"--max-count=[0-9]+", arg) for arg in rest)
    if exe in {"make", "gmake", "mingw32-make"}:
        index = 0
        while index < len(args):
            arg = args[index]
            if arg in {"-j", "--jobs"} and index + 1 < len(args) and args[index + 1].isdigit():
                index += 2
                continue
            if arg not in {"all", "build", "test", "check", "lint", "-j", "--jobs"} and not re.fullmatch(r"-j[0-9]+|--jobs=[0-9]+", arg):
                return False
            index += 1
        return True
    if exe in {"python", "python3", "py"}:
        if args[:2] != ["-m", "pytest"]:
            return False
        exe, args = "pytest", args[2:]
    if exe == "pytest":
        return all(arg in {"-q", "-v", "-vv", "-x", "--disable-warnings"}
                   or not arg.startswith("-") and (arg == "tests" or arg.startswith("tests/")
                                                   or arg.endswith(".py")) for arg in args)
    if exe == "npm":
        return args in (["test"], ["run", "build"], ["run", "test"], ["run", "check"], ["run", "lint"])
    if exe == "cmake":
        return (len(args) >= 2 and args[0] == "--build" and not args[1].startswith("-")
                and (len(args) == 2 or len(args) == 4 and args[2] == "--config"
                     and args[3] in {"Debug", "Release", "RelWithDebInfo", "MinSizeRel"}))
    if exe == "ctest":
        return all(arg in {"--output-on-failure", "-V", "--verbose"} for arg in args)
    return False
