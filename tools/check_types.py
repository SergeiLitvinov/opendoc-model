"""Verify positive/negative consumers against an installed wheel, away from src."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests/typing"
_ERROR = re.compile(r"consumer_bad\.py:(\d+): error: .*\[([a-z-]+)\]$")
_PROBE = """
import json
import sys
from importlib.metadata import distributions
from pathlib import Path
import opendoc_model
module = Path(opendoc_model.__file__).resolve()
assert module.is_relative_to(Path(sys.prefix).resolve()), module
assert (module.parent / 'py.typed').is_file()
assert {dist.metadata['Name'].lower() for dist in distributions()} == {'opendoc-model'}
print(json.dumps({'module': str(module), 'python': sys.executable}))
"""


def expected_errors(source):
    return {
        (index, line.split("# type-error: ", 1)[1].strip())
        for index, line in enumerate(source.splitlines(), 1)
        if "# type-error: " in line
    }


def verify(python):
    python = str(Path(python).absolute())
    with tempfile.TemporaryDirectory(prefix="typed-consumer-", dir=ROOT / ".opendoc") as directory:
        working = Path(directory)
        environment = dict(os.environ)
        environment.pop("MYPYPATH", None)
        environment.pop("PYTHONPATH", None)
        probe = subprocess.run(
            [python, "-I", "-c", _PROBE], cwd=working, env=environment, check=True, text=True, capture_output=True
        )
        print("Installed package: " + json.loads(probe.stdout)["module"])
        for name in ("consumer.py", "consumer_bad.py"):
            shutil.copyfile(FIXTURES / name, working / name)
        base = [
            sys.executable,
            "-I",
            "-m",
            "mypy",
            "--config-file",
            str(ROOT / "pyproject.toml"),
            "--python-executable",
            python,
            "--no-incremental",
            "--no-pretty",
            "--no-error-summary",
        ]
        positive = subprocess.run(base + ["consumer.py"], cwd=working, env=environment, text=True, capture_output=True)
        if positive.returncode != 0:
            raise RuntimeError("Typed consumer failed:\n" + positive.stdout + positive.stderr)
        negative = subprocess.run(base + ["consumer_bad.py"], cwd=working, env=environment, text=True, capture_output=True)
        actual = {
            (int(match[1]), match[2]) for line in negative.stdout.splitlines() if (match := _ERROR.search(line)) is not None
        }
        errors = [line for line in negative.stdout.splitlines() if ": error:" in line]
        expected = expected_errors((working / "consumer_bad.py").read_text(encoding="utf-8"))
        if negative.returncode != 1 or not expected or actual != expected or len(errors) != len(expected):
            raise RuntimeError("Expected consumer errors were not detected exactly:\n" + negative.stdout + negative.stderr)
        # If src/editable imports leak into this run, disabling site-packages
        # would still find OpenDoc Model. Require its installed imports to disappear.
        hidden = subprocess.run(
            base + ["--no-site-packages", "consumer.py"], cwd=working, env=environment, text=True, capture_output=True
        )
        if hidden.returncode != 1 or "[import-not-found]" not in hidden.stdout or '"opendoc_model"' not in hidden.stdout:
            raise RuntimeError(
                "Consumer unexpectedly found OpenDoc Model without installed packages:\n" + hidden.stdout + hidden.stderr
            )
        subprocess.run([python, "-I", "consumer.py"], cwd=working, env=environment, check=True)
        print(f"Installed types: positive consumer passed; all {len(expected)} deliberate errors detected; src excluded")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, help="Empty environment with only the OpenDoc Model wheel installed")
    verify(parser.parse_args().python)
