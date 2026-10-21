"""Runtime platform facts shared by chat brains and project workers."""

import sys


def host_instructions(*, worker_shell: bool = False) -> str:
    if sys.platform == "win32":
        text = (
            "Host environment: Windows. The owner uses PowerShell. "
            "Give Windows paths and PowerShell-compatible instructions to the owner. "
            "Prefer available .ps1, .cmd, .bat or Python entry points; inspect the "
            "project before choosing a script. Do not tell the owner to execute .sh "
            "files, chmod, sudo, source, or POSIX shell syntax directly on Windows. "
            "Do not assume WSL, Bash, Git Bash or Unix utilities are installed. "
            "If a project only supplies a .sh script, inspect it and find or implement "
            "a Windows-compatible route; use Bash/WSL only when explicitly selected "
            "and verified available. These runtime facts take precedence over "
            "Linux examples in documentation or earlier conversation."
        )
        if worker_shell:
            text += (
                " The run_command tool executes through cmd.exe on this host. "
                "Use cmd.exe-compatible commands there, or explicitly invoke "
                "powershell.exe -NoProfile -Command for PowerShell commands. "
                "Prefer shell=powershell to pass PowerShell code directly without nested quoting. "
                "Use run_python for Python code: it uses the project .venv when present (bridge interpreter fallback), avoiding "
                "Windows Store aliases and missing PATH entries. Commands already start in "
                "the project folder; no cd prefix is needed. Bash << heredocs, head, tail, "
                "and grep are not available by default. Use read_file with start_line and "
                "line_count to inspect source, rather than shell text pipelines. "
                "On command failure inspect stderr and correct the shell or executable; "
                "do not diagnose file encoding or missing Python from a shell syntax error."
            )
        return text
    return (
        f"Host environment: {sys.platform}. Use commands and paths compatible "
        "with this host; do not infer the platform from documentation examples."
    )
