"""Probe launchers must keep the venv interpreter alias on POSIX."""

import json
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from tools import check_math, check_wheel


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX interpreter symlink regression")
@pytest.mark.parametrize("tool", [check_wheel, check_math])
def test_probe_keeps_virtual_environment_interpreter_symlink(tmp_path, monkeypatch, tool):
    environment = tmp_path / "isolated"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    python = environment / "bin/python"
    assert python.is_symlink()
    location = subprocess.check_output(
        [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True
    ).strip()
    (Path(location) / "venv_probe.py").write_text("VALUE = 'isolated site-packages'\n", encoding="utf-8")
    probe = (
        "import sys, venv_probe; "
        f"assert sys.prefix == {json.dumps(str(environment))}; "
        "assert venv_probe.VALUE == 'isolated site-packages'"
    )
    monkeypatch.setattr(tool, "PROBE", probe)
    if tool is check_wheel:
        monkeypatch.setattr(check_wheel, "verify_math", lambda python: None)
    tool.verify(str(python))
