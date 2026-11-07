"""Launch visible .ps1 command heads through PowerShell, never file association.

This is a bounded CMD lexer, not intent detection or a general shell converter.
It preserves the surrounding CMD operators, arguments and redirections. Nested
CMD/control-flow involving scripts is refused rather than guessed.
"""
from __future__ import annotations

import re

POWERSHELL_FILE = 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File '
_REDIRECT = re.compile(r'\d*(?:>>|[<>])(?:&(?:\d+|-))?')


def _tokens(command):
    i = 0
    while i < len(command):
        if command[i] in ' \t\r':
            i += 1
            continue
        start = i
        redirect = _REDIRECT.match(command, i)
        if redirect:
            i = redirect.end()
            yield 'redirect', start, i, redirect.group()
            continue
        if command[i] in '&|()\n':
            i += 1
            if command[start] in '&|' and i < len(command) and command[i] == command[start]:
                i += 1
            yield 'operator', start, i, command[start:i]
            continue
        value = []
        quoted = False
        while i < len(command):
            char = command[i]
            if char == '^' and not quoted and i + 1 < len(command):
                value.append(command[i + 1])
                i += 2
                continue
            if char == '"':
                quoted = not quoted
                i += 1
                continue
            if not quoted and (char.isspace() or char in '&|()<>'):
                break
            value.append(char)
            i += 1
        if quoted:
            raise ValueError('Unbalanced CMD quoting; use shell=powershell with an explicit script invocation')
        yield 'word', start, i, ''.join(value)


def explicit_powershell_files(command: str) -> str:
    """Rewrite only script command heads, including heads following && and |.

    Never rewrite echo arguments, quoted program text, explicit interpreters or
    redirection filenames. No script contents, associations or settings are read.
    """
    if '.ps1' not in command.lower():
        return command
    tokens = list(_tokens(command))
    head = True
    redirect_target = False
    replacements = []
    for kind, start, end, value in tokens:
        if kind == 'redirect':
            redirect_target = '&' not in value
            continue
        if redirect_target and kind == 'word':
            redirect_target = False
            continue
        if kind == 'operator':
            head = True
            redirect_target = False
            continue
        if not head:
            continue
        word = value.lstrip('@').lower()
        if value == '@':
            continue
        if word == 'call':
            continue
        if word in {'if', 'for', 'start', 'cmd', 'cmd.exe'}:
            raise ValueError('CMD control-flow/nested launch containing .ps1 needs an explicit PowerShell invocation')
        head = False
        if not word.endswith('.ps1'):
            continue
        prefix = '@' if value.startswith('@') else ''
        path = value[len(prefix):]
        replacements.append((start, end, prefix + POWERSHELL_FILE + '"' + path + '"'))
    for start, end, replacement in reversed(replacements):
        command = command[:start] + replacement + command[end:]
    return command
