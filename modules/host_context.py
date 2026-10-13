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
                "powershell.exe -NoProfile -Command for PowerShell commands."
            )
        return text
    return (
        f"Host environment: {sys.platform}. Use commands and paths compatible "
        "with this host; do not infer the platform from documentation examples."
    )
