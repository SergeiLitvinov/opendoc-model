"""Dependency documentation must fail closed when versions, licenses or coverage drift."""

import json
import shutil

import pytest

from tools import dependencies


def copy_inventory(tmp_path):
    for name in ("pyproject.toml", "uv.lock", "docs/development/dependency-inventory.json", "docs/development/dependencies.md"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dependencies.ROOT / name, target)
    return tmp_path


def test_real_dependency_inventory_matches_locked_profiles_and_build_requirement():
    dependencies.verify(installed=False)
    values = dependencies.locked()
    assert values["lxml"]["profiles"] == ["math"]
    assert values["setuptools"]["profiles"] == ["build"]
    assert values["pathspec"]["profiles"] == ["dev", "docs"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["packages"].pop(),
        lambda data: data["packages"][0].update(version="0.0.0"),
        lambda data: data["packages"][0].update(license="Unknown"),
        lambda data: data["packages"][0].update(notices=[]),
    ],
)
def test_inventory_rejects_unreviewed_version_license_or_missing_evidence(tmp_path, mutation):
    root = copy_inventory(tmp_path)
    path = root / "docs/development/dependency-inventory.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    mutation(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        dependencies.verify(root, installed=False)


def test_dependency_table_must_include_all_locked_packages(tmp_path):
    root = copy_inventory(tmp_path)
    (root / "docs/development/dependencies.md").write_text("# Missing table", encoding="utf-8")
    with pytest.raises(ValueError, match="documentation is stale"):
        dependencies.verify(root, installed=False)


def test_platform_markers_keep_inventory_complete_and_filter_active_installation():
    complete = dependencies.locked()
    linux = dependencies.locked(environment={"sys_platform": "linux"})
    windows = dependencies.locked(environment={"sys_platform": "win32"})
    assert "colorama" in complete and "colorama" in windows and "colorama" not in linux
    assert linux["lxml"]["profiles"] == ["math"]
    assert set(linux) == set(complete) - {"colorama"}


def test_inactive_platform_package_is_not_required_in_installed_environment(monkeypatch):
    original = dependencies.importlib.metadata.distribution

    def distribution(name):
        if name == "colorama":
            raise AssertionError("inactive Windows-only package was requested")
        return original(name)

    monkeypatch.setattr(dependencies, "default_environment", lambda: {"sys_platform": "linux"})
    monkeypatch.setattr(dependencies.importlib.metadata, "distribution", distribution)
    dependencies.verify()


def test_missing_active_dependency_still_fails_the_installed_audit(monkeypatch):
    original = dependencies.importlib.metadata.distribution

    def distribution(name):
        if name == "lxml":
            raise dependencies.importlib.metadata.PackageNotFoundError(name)
        return original(name)

    monkeypatch.setattr(dependencies.importlib.metadata, "distribution", distribution)
    with pytest.raises(dependencies.importlib.metadata.PackageNotFoundError):
        dependencies.verify()
