from pathlib import Path

from pipeline import karta


def test_karta_lists_every_article():
    text = karta.build()
    articles = list((karta.WIKI / "Статьи").rglob("*.md"))
    assert text.startswith("---\ntype: карта")
    assert text.count("\n- [[") == len(articles)
    assert f"Статей: **{len(articles)}**" in text
    for p in articles:
        assert f"|{p.stem}]]" in text
