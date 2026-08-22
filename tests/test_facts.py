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

VIN JF1GDDLF37G076103 расшифровывается так.

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

NOTE_QUOTED = """---
tid: 2
---

# Тема с цитированием

##### Пост 200

*evil · 27.03.2012 15:00:00 · #1*

Передаточное отношение без разницы снимаш заднюю часть кпп и переставляеш в свою

##### Пост 201

*KOLESO · 27.03.2012 16:00:00 · #2*

> evil пишет:
> Передаточное отношение без разницы снимаш заднюю часть кпп и переставляеш в свою

Согласен с evil, тоже так делал.
"""


@pytest.fixture
def mirror(tmp_path):
    root = tmp_path / "Источники"
    root.mkdir()
    (root / "Тема 1.md").write_text(NOTE, encoding="utf-8")
    (root / "Тема 2.md").write_text(NOTE_QUOTED, encoding="utf-8")
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


def test_source_without_anchor_never_reaches_attribution_even_with_thread_data_present(mirror, conn):
    """Н2 ревью задачи 4: сноска на тему целиком (`Тема 1`, без якоря поста)
    отвергается на этапе `check_one` (см. `test_source_without_anchor_is_
    rejected_as_uncitable` ниже) — и поэтому НИКОГДА не доходит до
    `_lookup_meta`, даже если в `threads` есть подходящая строка. Раньше
    (до фикса) такой источник проходил и получал атрибуцию первого поста
    темы независимо от того, из какого поста цитата взята на самом деле —
    живой пример ревью: тема 25468, цитата из поста 223272 (alexk13)
    получала подпись поста 186484 (STiAMV)."""
    conn.execute("INSERT INTO threads(tid, author, started_at) VALUES (1, 'ОсновательТемы', '2014-10-11')")
    conn.commit()
    raw = [{"источник": "Тема 1", "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр"}]
    result = facts.check_all(raw, mirror, conn)
    assert result["проверено"] == []
    assert len(result["отброшено"]) == 1
    assert "якор" in result["отброшено"][0]["причина"].lower()


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


# --- ревью задачи 4: Н1, Н2, Н3, Н6, Н8 -------------------------------------


def test_quoting_another_participants_words_is_rejected(mirror):
    """Н1 (критично): форумная разметка `> <ник> пишет:` переносит в пост
    KOLESO слова evil. Якорь при этом правильной формы — без вычистки
    (см. `notes.FOREIGN_QUOTE`, коммит b14cb4dc) этот факт прошёл бы гейт с
    подписью KOLESO (живой пример ревью — тема 10045, пост 302526)."""
    fact = {"источник": "Тема 2#Пост 201",
            "цитата": "снимаш заднюю часть кпп и переставляеш в свою", "суть": "x"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok
    assert "генератор" in reason.lower()  # тот же класс отказа, что и текст генератора


def test_quoting_the_quote_marker_itself_is_also_rejected(mirror):
    """Та же находка: сама форумная разметка цитирования («evil пишет:»)
    тоже не слова KOLESO и тоже не должна проходить."""
    fact = {"источник": "Тема 2#Пост 201", "цитата": "evil пишет", "суть": "x"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok


def test_own_words_next_to_a_quote_block_still_pass(mirror):
    """Фикс Н1 не должен задевать честные слова автора СЕКЦИИ — они лежат
    рядом с чужим цитируемым блоком, а не внутри него."""
    fact = {"источник": "Тема 2#Пост 201", "цитата": "Согласен с evil, тоже так делал", "суть": "x"}
    ok, reason = facts.check_one(fact, mirror)
    assert ok, reason


def test_source_without_anchor_is_rejected_as_uncitable(mirror):
    """Н2: сноска на источник целиком остаётся законной ссылкой «см.
    также» в прозе, но подтвердить дословную цитату ей нечем."""
    fact = {"источник": "Тема 1", "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok
    assert "якор" in reason.lower()


def test_source_with_trailing_hash_and_no_anchor_is_rejected(mirror):
    """Н2, подпункт 2: хвостовая пустая решётка молча означала «источник
    целиком» — тот же дефект, что и полное отсутствие `#`."""
    fact = {"источник": "Тема 1#", "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok
    assert "якор" in reason.lower()


def test_anchor_outside_the_closed_list_is_rejected(mirror):
    """Н2, подпункт 3: форма якоря обязана входить в закрытый список видов
    сносок (`docs/контракт-зеркала.md` §1) — заголовок-контейнер вроде
    «Комментарии» (без номера, во множественном числе) якорем цитаты быть
    не может, даже если он реально существует как заголовок в заметке."""
    fact = {"источник": "Тема 1#Тормоза", "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok
    assert "список" in reason.lower() or "закрыт" in reason.lower()


def test_quote_shorter_than_minimum_length_is_rejected(mirror):
    """Н6: связь цитаты с полем «суть» машине недоступна, а связь цитаты с
    длиной — доступна. Двухсимвольная настоящая цитата с произвольной
    сутью не должна становиться честным проверенным фактом."""
    fact = {"источник": "Тема 1#Пост 100", "цитата": "мм",
            "суть": "любое утверждение, которого в источнике нет"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok
    assert "длин" in reason.lower()


def test_quote_of_pure_numbers_and_punctuation_is_rejected(mirror):
    """Короткий числовой фрагмент («025 / 2», 7 знаков) тоже короче
    порога — не только «голое слово»."""
    fact = {"источник": "Тема 1#Пост 100", "цитата": "025 / 2", "суть": "х"}
    ok, reason = facts.check_one(fact, mirror)
    assert not ok
    assert "длин" in reason.lower()


def test_quote_at_minimum_length_still_passes(mirror):
    """Порог не должен резать честные короткие технические цитаты — только
    вырожденный случай короче него."""
    fact = {"источник": "Тема 1#Пост 100", "цитата": "3/16 дюйма", "суть": "диаметр"}  # 10 знаков
    ok, reason = facts.check_one(fact, mirror)
    assert ok, reason


def test_single_word_technical_quote_is_not_rejected_by_length(mirror):
    """Ключевой сценарий, из-за которого порог считается в ЗНАКАХ, а не в
    СЛОВАХ (см. докстринг `facts.MIN_QUOTE_CHARS`): VIN, артикул, номер
    детали — законная и особенно ценная цитата этого домена, хотя это
    формально одно «слово». Счётчик слов отверг бы её (1 < 3); счётчик
    знаков — нет (17 знаков)."""
    fact = {"источник": "Тема 1#Пост 100", "цитата": "JF1GDDLF37G076103", "суть": "VIN"}
    ok, reason = facts.check_one(fact, mirror)
    assert ok, reason


def test_check_all_never_trusts_author_or_date_supplied_by_the_incoming_fact(mirror, conn):
    """Н3 (серьёзно): `автор`/`дата`, ЕСЛИ они пришли во входящем факте,
    снимаются БЕЗУСЛОВНО — до ветки с `conn`, а не только когда `conn`
    передан. Небезопасный режим не должен быть режимом по умолчанию."""
    conn.execute("INSERT INTO posts(mid, tid, author, posted_at, text, markdown) "
                 "VALUES (100, 1, 'Razum', '2014-10-11 12:00:00', '', '')")
    conn.commit()
    raw = [{"источник": "Тема 1#Пост 100", "цитата": "Трубки нужны 3/16 дюйма",
            "суть": "x", "автор": "ПОДДЕЛКА", "дата": "01.01.1999"}]

    with_conn = facts.check_all(raw, mirror, conn)
    assert with_conn["проверено"][0]["автор"] == "Razum"
    assert with_conn["проверено"][0]["дата"] == "11.10.2014"

    without_conn = facts.check_all(raw, mirror)
    fact = without_conn["проверено"][0]
    assert "автор" not in fact
    assert "дата" not in fact


# --- цитируемость источника (задача 6 Ф3, `notes.citable_source`) ----------
#
# `check_one` зовёт её только когда дан `conn` (как и атрибуцию выше) — без
# базы под рукой узнать про дубль/выдержку неоткуда, и это не должно
# становиться ложным «источник цитируем».


def test_duplicate_faq_entry_is_rejected_as_uncitable_with_conn(mirror, conn):
    """Дубль FAQ (`duplicate_of_nr` не пусто) — текст настоящий, но ссылаться
    нужно на каноническую (битриксовую) запись, не на дубль."""
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md, answer_text) "
                 "VALUES ('bitrix', 5, 'Как часто менять колодки?', 'Раз в 30 тысяч км', "
                 "'Раз в 30 тысяч км')")
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md, answer_text, "
                 "duplicate_of_engine, duplicate_of_nr) "
                 "VALUES ('old', 9, 'Как часто менять колодки?', 'Раз в 30 тысяч км', "
                 "'Раз в 30 тысяч км', 'bitrix', 5)")
    conn.commit()
    fact = {"источник": "FAQ старый 9#Ответ",
            "цитата": "Раз в 30 тысяч километров пробега", "суть": "интервал"}
    ok, reason = facts.check_one(fact, mirror, conn)
    assert not ok
    assert "дубл" in reason.lower()


def test_faq_without_conn_is_not_checked_for_duplicate_status(mirror):
    """Без `conn` проверка дублей просто не выполняется — не считается ни
    цитируемым, ни нецитируемым молча, а прежнее поведение (без базы)
    сохраняется."""
    fact = {"источник": "FAQ 5#Ответ", "цитата": "Раз в 30 тысяч километров пробега", "суть": "интервал"}
    ok, reason = facts.check_one(fact, mirror)
    assert ok, reason


def test_blog_excerpt_is_rejected_as_uncitable_with_conn(mirror, conn):
    """Выдержка блога (`is_excerpt=1`) — текст настоящий (восстановлен из
    ленты), но не тело записи (контракт зеркала §4)."""
    conn.execute("INSERT INTO blog_posts(blog, post_id, author, posted_at, body_md, is_excerpt) "
                 "VALUES ('remont', 42, 'ИгорьБлог', '09.08.2011 10:41:53', '', 1)")
    conn.commit()
    fact = {"источник": "Блог remont 42#Запись",
            "цитата": "Тормозные колодки нужно менять каждые 30 тысяч", "суть": "интервал"}
    ok, reason = facts.check_one(fact, mirror, conn)
    assert not ok
    assert "выдержка" in reason.lower()


def test_blog_record_without_excerpt_flag_still_passes_with_conn(mirror, conn):
    """Обычная (не выдержка) запись блога с `conn` под рукой по-прежнему
    проходит — новая проверка не должна задевать честные записи."""
    conn.execute("INSERT INTO blog_posts(blog, post_id, author, posted_at, body_md) "
                 "VALUES ('remont', 42, 'ИгорьБлог', '09.08.2011 10:41:53', '')")
    conn.commit()
    fact = {"источник": "Блог remont 42#Запись",
            "цитата": "Тормозные колодки нужно менять каждые 30 тысяч", "суть": "интервал"}
    ok, reason = facts.check_one(fact, mirror, conn)
    assert ok, reason


def test_lookup_meta_scopes_post_lookup_by_tid_not_only_mid(mirror, conn):
    """Н8 (мелочь, закрывается бесплатно): `mid` — первичный ключ `posts` и
    сам по себе уникален глобально, но проверка не должна держаться только
    на этом свойстве схемы (тот же класс несверенной перекрёстной связи,
    из которой в Ф2 выросли расхождения). Пост mid=100 реально принадлежит
    теме 1; источник заявляет тему 999 — атрибуция обязана отказать, а не
    подставить автора чужой темы."""
    conn.execute("INSERT INTO posts(mid, tid, author, posted_at, text, markdown) "
                 "VALUES (100, 1, 'Razum', '2014-10-11 12:00:00', '', '')")
    conn.commit()
    assert facts._lookup_meta("Тема 999#Пост 100", conn) == (None, None)
