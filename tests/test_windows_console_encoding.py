"""Native Unicode capture through the real Windows launcher, without reading settings."""
import base64
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from modules import version


@pytest.mark.skipif(os.name != 'nt' or not shutil.which('pwsh'), reason='Windows PowerShell host required')
@pytest.mark.parametrize('mode', ['no_window', 'hidden_new_console'])
@pytest.mark.parametrize('initialize', [False, True])
def test_windows_launcher_initializes_utf8_native_capture(tmp_path, mode, initialize):
    child = tmp_path / 'unicode child.py'
    child.write_text("import sys; sys.stdout.buffer.write(b'snowman-\\xe2\\x98\\x83')", encoding='ascii')
    launcher = Path(version.__file__).resolve().parents[1] / 'run-windows.ps1'
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    # Force the legacy context even on a UTF-8 developer console. -Help returns
    # before settings are read or any real bridge/dependency install is started.
    script = "[Console]::OutputEncoding=[Text.Encoding]::GetEncoding(437); "
    if initialize:
        script += '& ' + quote(launcher) + ' -Help | Out-Null; '
    script += ("$p=[Diagnostics.ProcessStartInfo]::new(); $p.FileName=" + quote(sys.executable)
        + '; $p.Arguments=' + quote(subprocess.list2cmdline([str(child)]))
        + '; $p.UseShellExecute=$false; $p.CreateNoWindow=$true; $p.RedirectStandardOutput=$true; '
        + '$c=[Diagnostics.Process]::Start($p); $actual=$c.StandardOutput.ReadToEnd(); $c.WaitForExit(); '
        + '$c.Dispose(); if($actual -ne ("snowman-"+[char]0x2603)){throw "Unicode capture mismatch"}')
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    flags = subprocess.CREATE_NO_WINDOW if mode == 'no_window' else subprocess.CREATE_NEW_CONSOLE
    result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-EncodedCommand',
        base64.b64encode(script.encode('utf-16-le')).decode('ascii')],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding='utf-8', errors='replace', timeout=20, creationflags=flags, startupinfo=startup)
    if initialize:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0 and 'Unicode capture mismatch' in result.stderr
