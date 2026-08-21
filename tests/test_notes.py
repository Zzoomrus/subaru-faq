from pathlib import Path
from pipeline import notes

NOTE = """---
tid: 42335
aliases: ["На Б10 ищу"]
---

# На Б10 ищу

##### Пост 391434

*Saka · 28.02.2015 18:35:30 · #1*

Ищу продольные рычаги (изображение не сохранилось: http://i.piccy.info/x.jpg)

##### Пост 391440

*Anri · 28.02.2015 21:10:32 · #2*

По 500р.
"""


def test_body_drops_frontmatter(tmp_path):
    p = tmp_path / "n.md"; p.write_text(NOTE, encoding="utf-8")
    assert "tid: 42335" not in notes.body(p)
    assert "# На Б10 ищу" in notes.body(p)


def test_section_ends_at_next_heading_of_any_level(tmp_path):
    p = tmp_path / "n.md"; p.write_text(NOTE, encoding="utf-8")
    s = notes.section(p, "Пост 391434")
    assert "Ищу продольные рычаги" in s
    assert "По 500р." not in s


def test_section_returns_none_for_missing_anchor(tmp_path):
    p = tmp_path / "n.md"; p.write_text(NOTE, encoding="utf-8")
    assert notes.section(p, "Пост 999999") is None


def test_citable_drops_generator_text(tmp_path):
    """Пометка об утрате — текст кода, а не автора.

    В зеркале таких 6341. Цитата, «подтверждённая» на этом тексте,
    подтверждает то, чего человек не писал, — и проверка при этом проходит.
    """
    p = tmp_path / "n.md"; p.write_text(NOTE, encoding="utf-8")
    s = notes.citable(notes.section(p, "Пост 391434"))
    assert "Ищу продольные рычаги" in s
    assert "изображение не сохранилось" not in s
    assert "28.02.2015" not in s          # строка «автор · дата» — тоже генератор


def test_citable_drops_empty_placeholders():
    assert "пустой комментарий" not in notes.citable("(пустой комментарий)\n\nреальный текст")
    assert "реальный текст" in notes.citable("(пустой комментарий)\n\nреальный текст")
