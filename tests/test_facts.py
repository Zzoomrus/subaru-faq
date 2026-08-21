import pytest

from pipeline import facts

NOTE = """---
tid: 1
---

# Тормоза

##### Пост 100

*Razum · 11.10.2014 12:00:00 · #1*

Трубки нужны 3/16 дюйма, это   4,75 мм. Резьба под ключ 11.

##### Пост 101

*Anri · 11.10.2014 13:00:00 · #2*

(изображение не сохранилось: http://i.piccy.info/x.jpg)
"""


@pytest.fixture
def mirror(tmp_path):
    root = tmp_path / "Источники"
    root.mkdir()
    (root / "Тема 1.md").write_text(NOTE, encoding="utf-8")
    return root


def test_verbatim_quote_passes(mirror):
    fact = {"источник": "Тема 1#Пост 100", "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр"}
    ok, reason = facts.check_one(fact, mirror)
    assert ok, reason


def test_whitespace_differences_do_not_reject(mirror):
    """Перенос строки и двойной пробел — не подделка цитаты."""
    fact = {"источник": "Тема 1#Пост 100", "цитата": "это 4,75 мм", "суть": "диаметр"}
    ok, reason = facts.check_one(fact, mirror)
    assert ok, reason


def test_altered_quote_is_rejected(mirror):
    fact = {"источник": "Тема 1#Пост 100", "цитата": "это 4,25 мм", "суть": "диаметр"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok
    assert "дословно" in reason


def test_quote_from_neighbouring_post_is_rejected(mirror):
    """Цитата есть в заметке, но НЕ в том посте, на который сноска."""
    fact = {"источник": "Тема 1#Пост 101", "цитата": "Резьба под ключ 11", "суть": "ключ"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok


def test_missing_anchor_is_rejected(mirror):
    fact = {"источник": "Тема 1#Пост 999", "цитата": "что угодно", "суть": "х"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok
    assert "якор" in reason.lower()


def test_missing_note_is_rejected(mirror):
    fact = {"источник": "Тема 777#Пост 100", "цитата": "что угодно", "суть": "х"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok


def test_generator_text_cannot_be_quoted(mirror):
    """Главная ловушка фазы: пометка об утрате есть в теле дословно.

    Без исключения текста генератора этот факт прошёл бы проверку и статья
    «подтвердила» бы слова, которых автор не писал.
    """
    fact = {"источник": "Тема 1#Пост 101",
            "цитата": "изображение не сохранилось", "суть": "картинка"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok
    assert "генератор" in reason.lower()


def test_check_all_numbers_facts_and_counts(mirror):
    raw = [
        {"источник": "Тема 1#Пост 100", "цитата": "Резьба под ключ 11", "суть": "ключ"},
        {"источник": "Тема 1#Пост 100", "цитата": "это 4,25 мм", "суть": "враньё"},
    ]
    result = facts.check_all(raw, mirror)
    assert [f["id"] for f in result["проверено"]] == ["f1"]
    assert len(result["отброшено"]) == 1
    assert result["статистика"] == {"всего": 2, "прошло": 1, "отброшено": 1}
