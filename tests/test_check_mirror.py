from pipeline import check_mirror


def test_detects_broken_link_and_anchor(tmp_path):
    (tmp_path / "Тема 1.md").write_text(
        "текст ^p100\n\nсм. [[Тема 2#^p999]] и [[Тема 404#^p1]]\n", encoding="utf-8")
    (tmp_path / "Тема 2.md").write_text("другой ^p200\n", encoding="utf-8")
    res = check_mirror.check(tmp_path)
    assert "Тема 404" in " ".join(res["broken_links"])
    assert "^p999" in " ".join(res["broken_anchors"])


def test_clean_mirror_has_no_findings(tmp_path):
    (tmp_path / "Тема 1.md").write_text("а ^p100\n\n[[Тема 2#^p200]]\n", encoding="utf-8")
    (tmp_path / "Тема 2.md").write_text("б ^p200\n", encoding="utf-8")
    res = check_mirror.check(tmp_path)
    assert res == {"broken_links": [], "broken_anchors": [], "duplicate_anchors": []}


def test_detects_duplicate_anchor(tmp_path):
    # На реальном корпусе межзаметочных ссылок пока нет вовсе (появятся в
    # следующей фазе), поэтому broken_links/broken_anchors там будут нулями
    # не потому что проверка не умеет их искать, а потому что нечему
    # сработать. duplicate_anchors ловится независимо от ссылок — этот тест
    # доказывает, что счётчик реагирует на заведомо повторённый якорь внутри
    # одной заметки.
    (tmp_path / "Тема 1.md").write_text(
        "первый ^p100\n\nвторой, ошибочно с тем же якорем ^p100\n", encoding="utf-8")
    res = check_mirror.check(tmp_path)
    assert any("^p100" in d and "2" in d for d in res["duplicate_anchors"])
    assert res["broken_links"] == []
    assert res["broken_anchors"] == []
