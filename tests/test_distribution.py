"""Release verification must reject contaminated or inconsistent artifacts."""

import io
import tarfile
import zipfile

import pytest

from tools.check_distribution import read_sdist, read_wheel

LICENSE = b"Approved license fixture"
PROJECT = b"""[project]
dynamic = ["version"]
[tool.setuptools.dynamic]
version = {attr = "opendoc_model.__version__"}
"""
METADATA = b"""Metadata-Version: 2.4
Name: opendoc-model
Version: 0.1.0
Requires-Python: >=3.11
License-Expression: MIT
License-File: docs/LICENSE
Provides-Extra: math
Provides-Extra: dev
Provides-Extra: docs
Requires-Dist: lxml>=5.0; extra == "math"
"""


def _wheel(path, change=None):
    entries = {
        "opendoc_model/__init__.py": b'__version__ = "0.1.0"\n',
        "opendoc_model/py.typed": b"",
        "opendoc_model-0.1.0.dist-info/METADATA": METADATA,
        "opendoc_model-0.1.0.dist-info/licenses/docs/LICENSE": LICENSE,
    }
    if change is not None:
        change(entries)
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in entries.items():
            archive.writestr(name, value)


@pytest.mark.parametrize(
    "change",
    [
        lambda entries: entries.update({"consumer_app/main.py": b""}),
        lambda entries: entries.update({"opendoc_model/__pycache__/model.pyc": b""}),
        lambda entries: entries.update({"opendoc_model-0.1.0.dist-info/licenses/docs/LICENSE": b"Different owner"}),
        lambda entries: entries.update({"opendoc_model-0.1.0.dist-info/METADATA": METADATA.replace(b"0.1.0", b"0.2.0")}),
        lambda entries: entries.update({"opendoc_model/__init__.py": b'__version__ = "0.2.0"\n'}),
    ],
)
def test_release_verifier_rejects_contaminated_or_inconsistent_wheel(tmp_path, change):
    path = tmp_path / "artifact.whl"
    _wheel(path)
    assert read_wheel(path, "0.1.0", LICENSE)["opendoc_model/py.typed"] == b""
    _wheel(path, change)
    with pytest.raises(ValueError):
        read_wheel(path, "0.1.0", LICENSE)


def test_release_verifier_rejects_duplicate_wheel_entry(tmp_path):
    path = tmp_path / "artifact.whl"
    _wheel(path)
    with zipfile.ZipFile(path, "a") as archive, pytest.warns(UserWarning, match="Duplicate"):
        archive.writestr("opendoc_model/py.typed", b"")
    with pytest.raises(ValueError, match="Duplicate"):
        read_wheel(path, "0.1.0", LICENSE)


@pytest.mark.parametrize(
    "unexpected", ["../outside", "src/consumer_app/main.py", "docs/.opendoc/cache", "tools/__pycache__/x.pyc"]
)
def test_release_verifier_rejects_sdist_contamination(tmp_path, unexpected):
    entries = {
        "PKG-INFO": METADATA,
        "docs/LICENSE": LICENSE,
        "src/opendoc_model/__init__.py": b'__version__ = "0.1.0"\n',
        "src/opendoc_model/py.typed": b"",
        "pyproject.toml": PROJECT,
    }
    path = tmp_path / "artifact.tar.gz"

    def write():
        with tarfile.open(path, "w:gz") as archive:
            for name, data in entries.items():
                member = tarfile.TarInfo("opendoc_model-0.1.0/" + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))

    write()
    assert read_sdist(path, "0.1.0", LICENSE)["docs/LICENSE"] == LICENSE
    entries[unexpected] = b"unwanted"
    write()
    with pytest.raises(ValueError):
        read_sdist(path, "0.1.0", LICENSE)


def test_wheel_source_verification_accepts_only_portable_newlines(tmp_path):
    from tools.check_distribution import _verify_sources

    package = tmp_path / "src/opendoc_model"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(b"value = 1\n")
    (package / "py.typed").write_bytes(b"")
    _verify_sources({"opendoc_model/__init__.py": b"value = 1\r\n", "opendoc_model/py.typed": b""}, tmp_path)


@pytest.mark.parametrize("change", ["missing", "extra", "changed"])
def test_wheel_source_verification_refuses_other_package_content(tmp_path, change):
    from tools.check_distribution import _verify_sources

    package = tmp_path / "src/opendoc_model"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(b"value = 1\n")
    contents = {"opendoc_model/__init__.py": b"value = 1\n"}
    if change == "missing":
        contents.clear()
    elif change == "extra":
        contents["opendoc_model/injected.py"] = b""
    else:
        contents["opendoc_model/__init__.py"] = b"value = 2\n"
    with pytest.raises(ValueError, match="source"):
        _verify_sources(contents, tmp_path)
