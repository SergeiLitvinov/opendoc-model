"""Documentation must reject stale references, broken links and escaping paths."""

from pathlib import Path

import pytest

from tools import docs


def project(tmp_path):
    source = tmp_path / "src/opendoc_model"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("from .model import Document as Document\n", encoding="utf-8")
    (source / "model.py").write_text('class Document:\n    """A document."""\n', encoding="utf-8")
    guide = tmp_path / "docs/guide"
    guide.mkdir(parents=True)
    (guide / "index.md").write_text("# Guide\n\n## Создать документ\n", encoding="utf-8")
    return tmp_path


def test_generation_tracks_symbols_and_rejects_source_drift(tmp_path):
    root = project(tmp_path)
    docs.sync(root=root)
    docs.sync(check=True, root=root)
    page = (root / "docs/reference/api.md").read_text(encoding="utf-8")
    assert "Document" in page and "model.py#L1" in page
    (root / "src/opendoc_model/model.py").write_text("\nclass Document: pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Stale generated"):
        docs.sync(check=True, root=root)


@pytest.mark.parametrize("url", ["missing.md", "guide/index.md#нет", "../../outside.md"])
def test_check_rejects_broken_links_and_escaping_paths(tmp_path, url):
    root = project(tmp_path)
    (root / "docs/index.md").write_text(f"# Index\n\n[bad]({url})", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid local link|missing anchor"):
        docs.prepare(root)


def test_source_pages_escape_markup_and_preserve_line_links(tmp_path):
    root = project(tmp_path)
    (root / "src/opendoc_model/model.py").write_text('x = "<script>alert(1)</script>"\n', encoding="utf-8")
    docs.prepare(root)
    page = root / ".opendoc/docs-source/files/src/opendoc_model/model.py.html"
    assert "&lt;script&gt;" in page.read_text(encoding="utf-8")
    assert 'id="L1"' in page.read_text(encoding="utf-8")


def test_real_documentation_is_current():
    docs.sync(check=True)
    assert Path(docs.ROOT / "docs/guide/index.md").is_file()
