"""The local XML typing boundary must still reject wrong options and value types."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

CODE = """
from lxml import etree
parser = etree.XMLParser(resolve_entities=False, load_dtd=False, dtd_validation=False,
    attribute_defaults=False, no_network=True, recover=False, huge_tree=False,
    remove_comments=True, remove_pis=True)
root = etree.fromstring(b'<math/>', parser)
root.set('id', '1')
value: str = etree.tostring(root, encoding='unicode')
"""


@pytest.mark.parametrize("invalid", [False, True])
def test_xml_calls_retain_static_validation(tmp_path, invalid):
    code = CODE + ("root.set('id', 1)\netree.fromstring(1, parser)\netree.XMLParser(no_netwrok=True)\n" if invalid else "")
    config = Path(__file__).resolve().parent.parent / "pyproject.toml"
    source = tmp_path / "xml_boundary.py"
    source.write_text(code, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", "-m", "mypy", "--config-file", str(config), "--no-incremental", "--no-error-summary", str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert result.returncode == int(invalid), result.stdout + result.stderr
    errors = re.findall(r"\[([a-z-]+)\]", result.stdout)
    assert errors == (["arg-type", "arg-type", "call-arg"] if invalid else []), result.stdout
