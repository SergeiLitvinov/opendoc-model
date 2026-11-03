"""Release tooling rejects unsafe versions and protects source/output boundaries."""

import hashlib

import pytest

from tools.release import assets, clean, plan, set_version


@pytest.mark.parametrize(
    ("selector", "expected"),
    [("current", "1.2.3"), ("patch", "1.2.4"), ("minor", "1.3.0"), ("major", "2.0.0"), ("2.3.4", "2.3.4")],
)
def test_version_planning(selector, expected):
    assert plan(selector, "1.2.3") == expected


@pytest.mark.parametrize("version", ["v1.2.3", "1.2", "01.2.3", "1.2.3rc1", "1.2.3\nversion=9.9.9", "1.2.2", "$(command)"])
def test_invalid_or_decreasing_release_cannot_modify_source(tmp_path, version):
    source = tmp_path / "src/opendoc_model/__init__.py"
    source.parent.mkdir(parents=True)
    original = '__version__ = "1.2.3"\nDOCUMENT_VERSION = 2\n'
    source.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        set_version(version, tmp_path)
    assert source.read_text(encoding="utf-8") == original
    assert not source.with_suffix(".py.tmp").exists()


def test_version_update_preserves_other_contracts_and_is_idempotent(tmp_path):
    source = tmp_path / "src/opendoc_model/__init__.py"
    source.parent.mkdir(parents=True)
    source.write_text('__version__ = "0.1.0"\nDOCUMENT_VERSION = 2\n', encoding="utf-8")
    set_version("0.2.0", tmp_path)
    set_version("0.2.0", tmp_path)
    assert source.read_text(encoding="utf-8") == '__version__ = "0.2.0"\nDOCUMENT_VERSION = 2\n'


def test_release_assets_are_exact_and_checksummed(tmp_path):
    source = tmp_path / "src/opendoc_model/__init__.py"
    source.parent.mkdir(parents=True)
    source.write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    names = ["opendoc_model-0.1.0-py3-none-any.whl", "opendoc_model-0.1.0.tar.gz"]
    for name in names:
        (dist / name).write_bytes(name.encode())
    (dist / ".gitignore").write_bytes(b"*")
    assets(dist, tmp_path)
    assert not (dist / ".gitignore").exists()
    expected = "".join(f"{hashlib.sha256(name.encode()).hexdigest()}  {name}\n" for name in names)
    assert (dist / "SHA256SUMS").read_text() == expected
    (dist / "private.log").write_text("unwanted")
    with pytest.raises(ValueError, match="unexpected"):
        assets(dist, tmp_path)
    assert (dist / "SHA256SUMS").read_text() == expected


def test_cleanup_preserves_source_environment_and_preview(tmp_path):
    preserved = [
        "README.md",
        "src/opendoc_model/__init__.py",
        ".venv/keep",
        ".opendoc/uv-cache/keep",
        ".opendoc/docs-site/index.html",
        ".opendoc/acceptance/consumer/wheel.whl",
        ".opendoc/acceptance/consumer/provenance.json",
    ]
    removed = ["build/old", "dist/old", ".opendoc/old-wheel/old", "tests/__pycache__/old"]
    for name in preserved + removed:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    clean(tmp_path)
    assert all((tmp_path / name).is_file() for name in preserved)
    assert all(not (tmp_path / name).exists() for name in removed)


def test_cleanup_rejects_external_symlink(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "outside"
    external.mkdir()
    protected = external / "keep"
    protected.write_text("outside project")
    try:
        (project / ".opendoc").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        clean(project)
    assert protected.is_file()
