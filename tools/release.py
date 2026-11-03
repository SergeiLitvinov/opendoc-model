"""Plan versions, validate release assets and clean disposable project output."""

import argparse
import hashlib
import os
import re
import shutil
from pathlib import Path

from tools.check_distribution import source_version, verify

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


def version_tuple(value):
    if not isinstance(value, str) or VERSION.fullmatch(value) is None:
        raise ValueError("Expected a stable version MAJOR.MINOR.PATCH without a v prefix")
    return tuple(map(int, value.split(".")))


def plan(selector, current):
    major, minor, patch = version_tuple(current)
    choices = {
        "current": current,
        "patch": f"{major}.{minor}.{patch + 1}",
        "minor": f"{major}.{minor + 1}.0",
        "major": f"{major + 1}.0.0",
    }
    result = choices.get(selector, selector)
    if version_tuple(result) < (major, minor, patch):
        raise ValueError("Release version cannot decrease")
    return result


def set_version(version, root=ROOT):
    path = root / "src/opendoc_model/__init__.py"
    text = path.read_text(encoding="utf-8")
    current = source_version(text)
    plan(version, current)
    if current == version:
        return
    updated, count = re.subn(r'^__version__ = "[^"]+"$', f'__version__ = "{version}"', text, flags=re.MULTILINE)
    if count != 1:
        raise ValueError("Expected one canonical version assignment")
    temporary = path.with_suffix(".py.tmp")
    try:
        temporary.write_text(updated, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def assets(dist, root=ROOT):
    version = source_version((root / "src/opendoc_model/__init__.py").read_bytes())
    names = [f"opendoc_model-{version}-py3-none-any.whl", f"opendoc_model-{version}.tar.gz"]
    directory = Path(dist)
    marker = directory / ".gitignore"
    if marker.exists():
        if marker.is_symlink() or marker.read_bytes() not in {b"*", b"*\n", b"*\r\n"}:
            raise ValueError("Unexpected build marker")
    if {path.name for path in directory.iterdir()} - {*names, "SHA256SUMS", ".gitignore"}:
        raise ValueError("Release directory contains unexpected files")
    for name in names:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing or unsafe release artifact: " + name)
    checksums = "".join(f"{hashlib.sha256((directory / name).read_bytes()).hexdigest()}  {name}\n" for name in names)
    (directory / "SHA256SUMS").write_text(checksums, encoding="utf-8", newline="\n")
    marker.unlink(missing_ok=True)
    return names


def clean(root=ROOT):
    root = root.resolve()
    keep = {
        "acceptance",
        "uv-cache",
        "docs-source",
        "docs-site",
        "performance-l16-before.json",
        "performance-l16-budget.json",
        "performance-l16-current.json",
        "performance-l16-old-mixed.json",
    }
    output = root / ".opendoc"
    targets = [
        root / name for name in ("build", "dist", ".pytest_cache", ".ruff_cache", ".mypy_cache", "src/opendoc_model.egg-info")
    ]
    if output.is_symlink():
        raise ValueError("Generated output directory must not be a symlink")
    if output.exists():
        targets.extend(path for path in output.iterdir() if path.name not in keep)
    targets.extend(path for base in ("src", "tests", "tools", "examples") for path in (root / base).rglob("__pycache__"))
    for path in targets:
        if not path.parent.resolve().is_relative_to(root):
            raise ValueError("Cleanup target escapes project: " + str(path))
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan").add_argument("selector", help="current, patch, minor, major or MAJOR.MINOR.PATCH")
    commands.add_parser("set").add_argument("version")
    bundle = commands.add_parser("assets")
    bundle.add_argument("--dist", default=".opendoc/release-dist")
    commands.add_parser("clean")
    args = parser.parse_args(argv)
    if args.command == "plan":
        version = plan(args.selector, source_version((ROOT / "src/opendoc_model/__init__.py").read_bytes()))
        print(version)
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
                stream.write(f"version={version}\n")
    elif args.command == "set":
        set_version(args.version)
    elif args.command == "assets":
        verify(args.dist)
        assets(args.dist)
    else:
        clean()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
