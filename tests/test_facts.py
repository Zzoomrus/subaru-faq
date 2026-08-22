import sqlite3

import pytest

from pipeline import db, facts

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


BLOG_NOTE = """# Блог: тормоза

##### Запись

Тормозные колодки нужно менять каждые 30 тысяч.

##### Комментарий 5

*Иван · 12.08.2011 16:43:51*

Согласен полностью.
"""

FAQ_NOTE = """# Как поменять колодки

##### Вопрос

Как часто менять колодки?

##### Ответ

Раз в 30 тысяч километров пробега.
"""


@pytest.fixture
def mirror(tmp_path):
    root = tmp_path / "Источники"
    root.mkdir()
    (root / "Тема 1.md").write_text(NOTE, encoding="utf-8")
    (root / "Блог remont 42.md").write_text(BLOG_NOTE, encoding="utf-8")
    (root / "FAQ 5.md").write_text(FAQ_NOTE, encoding="utf-8")
    return root


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    db.init_schema(c)
    return c


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


def test_ambiguous_note_name_is_rejected_with_its_own_reason(tmp_path):
    """Две заметки с одинаковым именем в РАЗНЫХ папках, ни одна не лежит по
    точному пути `Тема 1` — угадывать, какую имел в виду ИИ, нельзя.

    check_mirror.check в этой ситуации сверяет ОБЪЕДИНЕНИЕ якорей обеих
    заметок; для цитаты такая подмена недопустима — причина отказа обязана
    отличаться от «не найдена», это разные классы проблемы. (Заметка ровно
    по имени `Тема 1` в корне резолвилась бы точным путём раньше проверки
    неоднозначности — как и у Obsidian/check_mirror — поэтому здесь обе
    копии нарочно лежат в подпапках, без точного совпадения.)
    """
    root = tmp_path / "Источники"
    (root / "Раздел19").mkdir(parents=True)
    (root / "Раздел20").mkdir(parents=True)
    (root / "Раздел19" / "Тема 1.md").write_text(NOTE, encoding="utf-8")
    (root / "Раздел20" / "Тема 1.md").write_text(NOTE, encoding="utf-8")
    fact = {"источник": "Тема 1#Пост 100", "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр"}
    ok, reason = facts.check_one(fact, root)
    assert not ok
    assert "неоднозначн" in reason.lower()


# --- автор и дата факта — из базы, не из ответа ИИ -------------------------
#
# Следующая задача (сборка сноски) рендерит `[^f1]: «цитата» — Razum,
# 11.10.2014, [[Тема 42335#Пост 248484]]`, и подпись обязан набирать код:
# если бы имя/дату не проверял никто, ИИ мог бы подписать чужую цитату
# правдоподобным, но не своим именем.


def test_check_all_without_conn_does_not_add_author_or_date(mirror):
    """Без базы под рукой (программные вызовы, тесты) — ключи `автор`/`дата`
    у прошедшего факта попросту отсутствуют, а не становятся `None`
    незапрошенно."""
    raw = [{"источник": "Тема 1#Пост 100", "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр"}]
    result = facts.check_all(raw, mirror)
    fact = result["проверено"][0]
    assert "автор" not in fact
    assert "дата" not in fact


def test_check_all_attaches_author_and_date_from_forum_post(mirror, conn):
    conn.execute("INSERT INTO posts(mid, tid, author, posted_at, text, markdown) "
                 "VALUES (100, 1, 'Razum', '2014-10-11 12:00:00', '', '')")
    conn.commit()
    raw = [{"источник": "Тема 1#Пост 100", "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр"}]
    result = facts.check_all(raw, mirror, conn)
    fact = result["проверено"][0]
    assert fact["автор"] == "Razum"
    assert fact["дата"] == "11.10.2014"


def test_check_all_falls_back_to_thread_starter_when_source_has_no_anchor(mirror, conn):
    """Сноска на тему целиком (`[[Тема 1]]`, без якоря поста) — автор и дата
    берутся у ПЕРВОГО сообщения темы (`threads`), а не у поста из якоря,
    которого в источнике нет вовсе."""
    conn.execute("INSERT INTO threads(tid, author, started_at) VALUES (1, 'ОсновательТемы', '2014-10-11')")
    conn.commit()
    raw = [{"источник": "Тема 1", "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр"}]
    result = facts.check_all(raw, mirror, conn)
    fact = result["проверено"][0]
    assert fact["автор"] == "ОсновательТемы"
    assert fact["дата"] == "11.10.2014"


def test_check_all_attaches_author_and_date_from_blog_post(mirror, conn):
    conn.execute("INSERT INTO blog_posts(blog, post_id, author, posted_at, body_md) "
                 "VALUES ('remont', 42, 'ИгорьБлог', '09.08.2011 10:41:53', '')")
    conn.commit()
    raw = [{"источник": "Блог remont 42#Запись",
            "цитата": "Тормозные колодки нужно менять каждые 30 тысяч", "суть": "интервал"}]
    result = facts.check_all(raw, mirror, conn)
    fact = result["проверено"][0]
    assert fact["автор"] == "ИгорьБлог"
    assert fact["дата"] == "09.08.2011"


def test_check_all_attaches_author_and_date_from_blog_comment(mirror, conn):
    """Комментарий несёт СВОИ автора и дату — отдельные от записи, к которой
    он привязан."""
    conn.execute("INSERT INTO blog_posts(blog, post_id, author, posted_at, body_md) "
                 "VALUES ('remont', 42, 'ИгорьБлог', '09.08.2011 10:41:53', '')")
    conn.execute("INSERT INTO blog_comments(blog, post_id, comment_id, author, posted_at) "
                 "VALUES ('remont', 42, 5, 'Иван', '12.08.2011 16:43:51')")
    conn.commit()
    raw = [{"источник": "Блог remont 42#Комментарий 5", "цитата": "Согласен полностью", "суть": "согласие"}]
    result = facts.check_all(raw, mirror, conn)
    fact = result["проверено"][0]
    assert fact["автор"] == "Иван"
    assert fact["дата"] == "12.08.2011"


def test_faq_never_gets_author_or_date_even_with_matching_db_row(mirror, conn):
    """FAQ — база знаний, не реплика форумчанина: настоящего автора нет, а
    `snapshot_ts` — момент, когда запись СНЯЛ краулер, а не когда её
    написали. Подставить его в «дату» значило бы приписать записи чужую
    (архивную) дату как будто авторскую — обман того же рода, для защиты от
    которого проверяется дословность цитаты."""
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md, snapshot_ts) "
                 "VALUES ('bitrix', 5, 'Как часто менять колодки?', 'Раз в 30 тысяч км', '20220101120000')")
    conn.commit()
    raw = [{"источник": "FAQ 5#Ответ", "цитата": "Раз в 30 тысяч километров пробега", "суть": "интервал"}]
    result = facts.check_all(raw, mirror, conn)
    fact = result["проверено"][0]
    assert fact["автор"] is None
    assert fact["дата"] is None


def test_only_date_handles_iso_datetime():
    assert facts._only_date("2014-10-11 12:00:00") == "11.10.2014"


def test_only_date_handles_iso_date_without_time():
    assert facts._only_date("2014-10-11") == "11.10.2014"


def test_only_date_handles_already_ru_formatted_datetime():
    assert facts._only_date("11.10.2014 12:00:00") == "11.10.2014"


def test_only_date_handles_missing_value():
    assert facts._only_date(None) is None
    assert facts._only_date("") is None
