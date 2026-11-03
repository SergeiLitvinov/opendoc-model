"""Check the reviewed dependency inventory against the lockfile and installed notices."""

import argparse
import hashlib
import importlib.metadata
import json
import tomllib
from pathlib import Path

from packaging.markers import Marker, default_environment

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "docs/development/dependency-inventory.json"
LICENSES = {
    "ast-serialize": "MIT",
    "click": "BSD-3-Clause",
    "colorama": "BSD-3-Clause",
    "ghp-import": "Apache-2.0",
    "iniconfig": "MIT",
    "jinja2": "BSD-3-Clause",
    "librt": "MIT",
    "lxml": "BSD-3-Clause",
    "markdown": "BSD-3-Clause",
    "markupsafe": "BSD-3-Clause",
    "mergedeep": "MIT",
    "mkdocs": "BSD-2-Clause",
    "mkdocs-get-deps": "MIT",
    "mypy": "MIT",
    "mypy-extensions": "MIT",
    "packaging": "Apache-2.0 OR BSD-2-Clause",
    "pathspec": "MPL-2.0",
    "platformdirs": "MIT",
    "pluggy": "MIT",
    "pygments": "BSD-2-Clause",
    "pytest": "MIT",
    "python-dateutil": "Apache-2.0 OR BSD-3-Clause",
    "pyyaml": "MIT",
    "pyyaml-env-tag": "MIT",
    "ruff": "MIT",
    "six": "MIT",
    "typing-extensions": "PSF-2.0",
    "watchdog": "Apache-2.0",
    "setuptools": "MIT",
}


def locked(root=ROOT, environment=None):
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    packages = {item["name"]: item for item in lock["package"]}
    roles = {name: set() for name in packages if name != "opendoc-model"}
    for profile, dependencies in packages["opendoc-model"].get("optional-dependencies", {}).items():
        pending = list(dependencies)
        seen = set()
        while pending:
            dependency = pending.pop()
            marker = dependency.get("marker")
            if environment is not None and marker and not Marker(marker).evaluate({**environment, "extra": profile}):
                continue
            name = dependency["name"]
            if name in seen:
                continue
            seen.add(name)
            roles[name].add(profile)
            pending.extend(packages[name].get("dependencies", []))
    result = {
        name: {
            "name": name,
            "version": packages[name]["version"],
            "profiles": sorted(profiles),
            "dependencies": sorted(item["name"] for item in packages[name].get("dependencies", [])),
        }
        for name, profiles in roles.items()
        if profiles or environment is None
    }
    (requirement,) = project["build-system"]["requires"]
    name, version = requirement.split("==")
    result[name] = {"name": name, "version": version, "profiles": ["build"], "dependencies": []}
    return result


def notices(distribution):
    result = []
    for file in distribution.files or []:
        if any(word in file.name.lower() for word in ("license", "copying", "notice", "copyright")):
            path = Path(distribution.locate_file(file))
            if not path.is_file():
                raise ValueError(f"Missing distributed notice: {file}")
            payload = path.read_bytes()
            result.append({"path": file.as_posix(), "sha256": hashlib.sha256(payload).hexdigest()})
    if not result:
        raise ValueError(f"No license evidence for {distribution.metadata['Name']}")
    return sorted(result, key=lambda value: value["path"])


def generate(build_dir):
    records = []
    for name, record in sorted(locked().items()):
        if name not in LICENSES:
            raise ValueError(f"New dependency needs license review: {name}")
        if name == "setuptools":
            distribution = importlib.metadata.Distribution.at(Path(build_dir) / f"setuptools-{record['version']}.dist-info")
        else:
            distribution = importlib.metadata.distribution(name)
        if distribution.version != record["version"]:
            raise ValueError(f"Installed version differs from the lock: {name}")
        expression = distribution.metadata.get("License-Expression")
        if expression is not None and expression != LICENSES[name]:
            raise ValueError(f"License expression needs review: {name}: {expression}")
        records.append({**record, "license": LICENSES[name], "notices": notices(distribution)})
    data = {
        "format": "opendoc.dependency-inventory",
        "version": 1,
        "scope": "reviewed Windows wheels; package-level licenses",
        "packages": records,
    }
    INVENTORY.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path = ROOT / "docs/development/dependencies.md"
    content = path.read_text(encoding="utf-8")
    begin, end = "<!-- dependency-table:start -->", "<!-- dependency-table:end -->"
    table = "| Пакет | Версия в lock/build | Профиль | Основная лицензия |\n| --- | --- | --- | --- |\n"
    table += "".join(
        f"| `{item['name']}` | {item['version']} | {', '.join(item['profiles'])} | {item['license']} |\n" for item in records
    )
    before, rest = content.split(begin)
    _, after = rest.split(end)
    path.write_text(before + begin + "\n\n" + table + "\n" + end + after, encoding="utf-8")


def verify(root=ROOT, installed=True):
    snapshot = json.loads((root / "docs/development/dependency-inventory.json").read_text(encoding="utf-8"))
    recorded = {item["name"]: item for item in snapshot["packages"]}
    current = locked(root)
    active = locked(root, default_environment()) if installed else {}
    if set(current) != set(recorded):
        raise ValueError("Dependency set changed; review and regenerate the inventory")
    guide = (root / "docs/development/dependencies.md").read_text(encoding="utf-8")
    for name, expected in current.items():
        item = recorded[name]
        if any(item[field] != value for field, value in expected.items()) or item["license"] != LICENSES.get(name):
            raise ValueError(f"Dependency contract changed: {name}")
        if f"| `{name}` | {item['version']} | {', '.join(item['profiles'])} | {item['license']} |" not in guide:
            raise ValueError(f"Dependency documentation is stale: {name}")
        if not item["notices"] or any(len(notice["sha256"]) != 64 for notice in item["notices"]):
            raise ValueError(f"Missing license evidence: {name}")
        if installed and name in active and name != "setuptools":
            distribution = importlib.metadata.distribution(name)
            if distribution.version != item["version"]:
                raise ValueError(f"Installed dependency differs from lock: {name}")
            expression = distribution.metadata.get("License-Expression")
            if expression is not None and expression != item["license"]:
                raise ValueError(f"License expression changed: {name}")
            notices(distribution)
    print(f"Dependencies: all {len(current)} locked/build packages documented with reviewed license evidence")


def verify_site(directory):
    site = Path(directory)
    for name in ("css", "js", "webfonts"):
        if (site / name).exists():
            raise ValueError(f"Unused third-party theme assets in site: {name}")
    assets = {
        "search/lunr.js": "contrib/search/templates/search/lunr.js",
        "search/lunr.ru.js": "contrib/search/lunr-language/lunr.ru.js",
        "search/lunr.multi.js": "contrib/search/lunr-language/lunr.multi.js",
        "search/lunr.stemmer.support.js": "contrib/search/lunr-language/lunr.stemmer.support.js",
    }
    distribution = importlib.metadata.distribution("mkdocs")
    for path, source in assets.items():
        if (site / path).read_bytes() != Path(distribution.locate_file("mkdocs/" + source)).read_bytes():
            raise ValueError(f"Published search source changed: {path}")
    for license in ("lunr-LICENSE.txt", "lunr-languages-LICENSE.txt", "umd-LICENSE.txt", "mkdocs-LICENSE.txt"):
        if not (site / f"files/docs/licenses/{license}.html").is_file():
            raise ValueError(f"Missing published license: {license}")
    if 'href="css/' in (site / "404.html").read_text(encoding="utf-8"):
        raise ValueError("404 page references removed vendor CSS")
    print("Site: unchanged search sources and full notices present; unused fonts/vendor theme assets omitted")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "generate"])
    parser.add_argument("--build-dir", default=".opendoc/build-license")
    parser.add_argument("--site", help="Also verify the built site's licensed assets")
    arguments = parser.parse_args()
    if arguments.command == "generate":
        generate(arguments.build_dir)
    else:
        verify()
        if arguments.site:
            verify_site(arguments.site)
