"""Rebuild generated inventories in the disposable source tree during preview."""

import os

from tools.docs import prepare


def on_config(config):
    repository = os.environ.get("GITHUB_REPOSITORY")
    if repository:
        owner, name = repository.split("/")
        config.repo_url = "https://github.com/" + repository
        config.site_url = f"https://{owner}.github.io/{name}/"
    return config


def on_pre_build(config):
    prepare()


def on_files(files, config):
    """The custom theme uses its own assets; omit unused vendor fonts/CSS/JS."""
    for file in list(files):
        if file.src_uri.startswith(("css/", "js/", "webfonts/")) or file.src_uri == "img/favicon.ico":
            files.remove(file)
    return files
