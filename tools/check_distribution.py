"""Verify release metadata, archive boundaries and wheel rebuilt from sdist."""

import argparse
import ast
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = {".git", ".venv", ".opendoc", ".pytest_cache", ".ruff_cache", ".mypy_cache", "__pycache__", "build", "dist"}
ROOT_FILES = {
    "README.md",
    "mkdocs.yml",
    "uv.lock",
    "pyproject.toml",
    "MANIFEST.in",
    "PKG-INFO",
    "setup.cfg",
}


def source_version(payload):
    values = [
        ast.literal_eval(node.value)
        for node in ast.parse(payload).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
    ]
    if len(values) != 1 or not isinstance(values[0], str):
        raise ValueError("Expected one literal version")
    return values[0]


def safe_path(name):
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in name or set(path.parts) & FORBIDDEN:
        raise ValueError("Forbidden archive path: " + name)
    return path.parts


def check_metadata(payload, version):
    data = BytesParser().parsebytes(payload)
    expected = {"Name": "opendoc-model", "Version": version, "Requires-Python": ">=3.11", "License-Expression": "MIT"}
    if any(data[key] != value for key, value in expected.items()):
        raise ValueError("Incorrect release metadata")
    if data.get_all("License-File") != ["docs/LICENSE"] or set(data.get_all("Provides-Extra", [])) != {"math", "dev", "docs"}:
        raise ValueError("Incorrect license or extras metadata")
    if any("extra ==" not in item for item in data.get_all("Requires-Dist", [])):
        raise ValueError("Unexpected core dependency")


def read_wheel(path, version, license_bytes):
    info = f"opendoc_model-{version}.dist-info"
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate wheel entries")
        for name in names:
            parts = safe_path(name)
            package = parts[0] == "opendoc_model" and (name.endswith(".py") or name == "opendoc_model/py.typed")
            metadata = name in {
                f"{info}/{entry}" for entry in ("METADATA", "WHEEL", "RECORD", "top_level.txt", "licenses/docs/LICENSE")
            }
            if not package and not metadata:
                raise ValueError("Unexpected wheel entry: " + name)
        contents = {name: archive.read(name) for name in names}
    check_metadata(contents[f"{info}/METADATA"], version)
    if contents[f"{info}/licenses/docs/LICENSE"] != license_bytes or "opendoc_model/py.typed" not in contents:
        raise ValueError("Missing or incorrect license/py.typed")
    if source_version(contents["opendoc_model/__init__.py"]) != version:
        raise ValueError("Wheel source version differs from metadata")
    return contents


def read_sdist(path, version, license_bytes):
    contents = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            parts = safe_path(member.name)
            if not parts or parts[0] != f"opendoc_model-{version}" or not (member.isfile() or member.isdir()):
                raise ValueError("Unexpected sdist entry: " + member.name)
            if member.isdir():
                continue
            name = str(PurePosixPath(*parts[1:]))
            allowed = name in ROOT_FILES if len(parts) == 2 else parts[1] in {"src", "docs", "tools", "tests", "examples"}
            if parts[1] == "src":
                allowed = len(parts) > 2 and parts[2] in {"opendoc_model", "opendoc_model.egg-info"}
            if not allowed or name in contents or name.endswith((".pyc", ".pyo")):
                raise ValueError("Unexpected/duplicate sdist payload: " + name)
            stream = archive.extractfile(member)
            assert stream is not None
            contents[name] = stream.read()
    check_metadata(contents["PKG-INFO"], version)
    if contents["docs/LICENSE"] != license_bytes or "src/opendoc_model/py.typed" not in contents:
        raise ValueError("Missing or incorrect sdist license/py.typed")
    project = tomllib.loads(contents["pyproject.toml"].decode("utf-8"))
    if "version" in project["project"] or project["tool"]["setuptools"]["dynamic"]["version"] != {
        "attr": "opendoc_model.__version__"
    }:
        raise ValueError("Expected single runtime version source")
    if source_version(contents["src/opendoc_model/__init__.py"]) != version:
        raise ValueError("Sdist version differs from metadata")
    return contents


def _verify_sources(contents, root=ROOT):
    """Accept portable text newlines, but no changed or missing package sources."""
    directory = root / "src/opendoc_model"
    expected = {
        "opendoc_model/" + path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file() and (path.suffix == ".py" or path.name == "py.typed")
    }
    actual = {name: value for name, value in contents.items() if name.startswith("opendoc_model/")}
    if actual.keys() != expected.keys():
        raise ValueError("Wheel package source set differs from checkout")
    for name, value in expected.items():
        if actual[name].replace(b"\r\n", b"\n") != value.replace(b"\r\n", b"\n"):
            raise ValueError("Wheel source differs from checkout: " + name)


def verify(dist, rebuilt=None):
    version = source_version((ROOT / "src/opendoc_model/__init__.py").read_bytes())
    license_bytes = (ROOT / "docs/LICENSE").read_bytes()
    wheel = read_wheel(Path(dist) / f"opendoc_model-{version}-py3-none-any.whl", version, license_bytes)
    _verify_sources(wheel)
    sdist = read_sdist(Path(dist) / f"opendoc_model-{version}.tar.gz", version, license_bytes)
    for name, value in wheel.items():
        if name.startswith("opendoc_model/") and sdist.get("src/" + name) != value:
            raise ValueError("Wheel/sdist package disagreement: " + name)
    if rebuilt is not None and wheel != read_wheel(
        Path(rebuilt) / f"opendoc_model-{version}-py3-none-any.whl", version, license_bytes
    ):
        raise ValueError("Rebuilt wheel payload differs from direct wheel")
    print(f"Release {version}: license, metadata, archive boundaries and package parity OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", required=True)
    parser.add_argument("--rebuilt", help="Directory containing wheel rebuilt from sdist")
    args = parser.parse_args()
    verify(args.dist, args.rebuilt)
