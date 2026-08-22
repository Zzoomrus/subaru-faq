"""Тесты отчёта покрытия (задача 6).

Формула брифа `COALESCE(replies_expected, 0) + 1` неверна: у 1612 тем
(созданных фолбэком `ensure_thread_from_page`, см. `pipeline.ingest`)
`replies_expected IS NULL`, потому что темы нет ни в одном оглавлении —
"ожидание 1 пост" для них было бы ложью, а не отсутствием данных.
Поэтому отчёт делит темы на пять групп, а не на четыре счётчика брифа:

- `ok`           — тема из оглавления, `got == expected`;
- `short`        — тема из оглавления, `got < expected` (и got > 0);
- `extra`        — тема из оглавления, `got > expected`;
- `missing`      — тема из оглавления, постов вообще нет (`got == 0`);
- `unverifiable` — `replies_expected IS NULL`, сверять не с чем.

Приоритет классификации: `unverifiable` проверяется первым (нет `expected`
— неважно, сколько постов), затем `missing` (`got == 0`), затем знак `diff`.
На реальных данных `unverifiable` и `missing` не пересекаются (фолбэк
создаёт строку `threads` только когда у страницы есть хотя бы один пост —
см. `ingest.ensure_thread_from_page`), но порядок проверок закладывает это
как инвариант, а не как случайное совпадение.
"""
from pipeline import db, coverage, facts


def _seed(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    db.init_schema(conn)
    threads = [
        (1, 19, "полная", 2),        # 3 поста ожидается (2+1), 3 есть -> ok
        (2, 19, "неполная", 5),      # 6 ожидается, 1 есть -> short
        (3, 19, "пустая", 1),        # 2 ожидается, 0 есть -> missing
        (4, 19, "с довеском", 1),    # 2 ожидается, 3 есть -> extra
        (5, 19, "без оглавления", None),  # replies_expected NULL -> unverifiable
    ]
    for tid, fid, title, replies_expected in threads:
        conn.execute(
            "INSERT INTO threads(tid, fid, title, replies_expected) VALUES (?,?,?,?)",
            (tid, fid, title, replies_expected))
    posts = [
        (10, 1), (11, 1), (12, 1),   # тема 1: 3 поста
        (20, 2),                     # тема 2: 1 пост
        (30, 4), (31, 4), (32, 4),   # тема 4: 3 поста
        (40, 5),                     # тема 5: 1 пост, но нечем сверить
    ]
    for mid, tid in posts:
        conn.execute("INSERT INTO posts(mid, tid, page_no, text) VALUES (?,?,1,'x')", (mid, tid))
    conn.commit()
    return conn


def test_report_flags_groups_and_diff(tmp_path):
    rows = {r.tid: r for r in coverage.report(_seed(tmp_path))}

    assert rows[1].group == "ok"
    assert rows[1].expected == 3
    assert rows[1].got == 3
    assert rows[1].diff == 0

    assert rows[2].group == "short"
    assert rows[2].diff == -5

    assert rows[3].group == "missing"
    assert rows[3].got == 0
    assert rows[3].expected == 2
    assert rows[3].diff == -2

    assert rows[4].group == "extra"
    assert rows[4].diff == 1

    assert rows[5].group == "unverifiable"
    assert rows[5].expected is None
    assert rows[5].diff is None
    assert rows[5].got == 1


def test_summary_counts(tmp_path):
    s = coverage.summary(coverage.report(_seed(tmp_path)))
    assert s == {
        "threads": 5,
        "ok": 1,
        "short": 1,
        "extra": 1,
        "missing": 1,
        "unverifiable": 1,
    }


def test_null_expected_thread_with_zero_posts_is_unverifiable_not_missing(tmp_path):
    # Инвариант из docstring модуля: на реальных данных такого не бывает
    # (фолбэк создаёт threads только когда у страницы есть посты), но
    # классификация не должна путать "нечем сверить" с "постов нет" —
    # приоритет unverifiable выше missing.
    conn = db.connect(tmp_path / "t2.sqlite")
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO threads(tid, fid, title, replies_expected) VALUES (6, 19, 'без постов и без оглавления', NULL)")
    conn.commit()
    rows = coverage.report(conn)
    assert len(rows) == 1
    assert rows[0].group == "unverifiable"
    assert rows[0].got == 0


def test_to_csv_includes_group_column(tmp_path):
    rows = coverage.report(_seed(tmp_path))
    out = tmp_path / "coverage.csv"
    coverage.to_csv(rows, out)
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert "group" in header.split(",")


def test_to_csv_has_bom_and_writes_rows(tmp_path):
    # CSV этого отчёта смотрят в Excel — без BOM русская Windows покажет
    # кракозябры. Заодно проверяем сами строки, а не только заголовок.
    from pipeline import coverage
    rows = [coverage.Row(tid=1, fid=19, title="Тормоза", expected=3, got=3, diff=0, group="ok"),
            coverage.Row(tid=2, fid=19, title="Мосты", expected=None, got=1, diff=None,
                         group="unverifiable")]
    path = tmp_path / "coverage.csv"
    coverage.to_csv(rows, path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "BOM нужен Excel'ю"
    lines = raw.decode("utf-8-sig").splitlines()
    assert lines[1] == "1,19,Тормоза,3,3,0,ok"
    assert lines[2] == "2,19,Мосты,,1,,unverifiable"


# --- задача 7 Ф3: покрытие FAQ/блогов + доля непроцитированных источников --


def _faq_row(conn, engine, nr, answer_md="", answer_text="", dup_engine=None, dup_nr=None):
    conn.execute(
        "INSERT INTO faq(engine, nr, question, answer_md, answer_text, "
        "duplicate_of_engine, duplicate_of_nr) VALUES (?,?,?,?,?,?,?)",
        (engine, nr, "вопрос %s%d" % (engine, nr), answer_md, answer_text, dup_engine, dup_nr))


def _blog_row(conn, blog, post_id, body_md="", body_text="", is_excerpt=0):
    conn.execute(
        "INSERT INTO blog_posts(blog, post_id, body_md, body_text, is_excerpt) "
        "VALUES (?,?,?,?,?)",
        (blog, post_id, body_md, body_text, is_excerpt))


def _seed_faq_blog(tmp_path):
    conn = db.connect(tmp_path / "fb.sqlite")
    db.init_schema(conn)
    # FAQ: с текстом, дубль, из одних картинок, пустой ответ.
    _faq_row(conn, "bitrix", 1, "Лей полусинтетику.", "Лей полусинтетику.")
    _faq_row(conn, "old", 2, "Лей полусинтетику.", "Лей полусинтетику.",
             dup_engine="bitrix", dup_nr=1)
    _faq_row(conn, "bitrix", 3, "![[assets/x.jpg]]", "")           # из одних картинок
    _faq_row(conn, "bitrix", 4, "", "")                             # пустой ответ вовсе
    # Блоги: с текстом, выдержка, из одних картинок.
    _blog_row(conn, "remont", 10, "Заменил ремень.", "Заменил ремень.")
    _blog_row(conn, "remont", 11, "Обрывок из ленты.", "Обрывок из ленты.", is_excerpt=1)
    _blog_row(conn, "remont", 12, "![[assets/y.jpg]]", "")          # из одних картинок
    conn.commit()
    return conn


def test_faq_blog_coverage_partitions_records_without_overlap(tmp_path):
    conn = _seed_faq_blog(tmp_path)
    result = coverage.faq_blog_coverage(conn)

    assert result["faq"] == {
        "всего": 4, "дублей": 1, "из_одних_картинок": 1, "пустых": 1, "с_текстом": 1,
    }
    assert result["блоги"] == {
        "всего": 3, "выдержек": 1, "из_одних_картинок": 1, "с_текстом": 1,
    }
    # Группы не пересекаются — сумма обязана сходиться в "всего" (иначе
    # запись посчиталась бы дважды или потерялась).
    faq = result["faq"]
    assert faq["дублей"] + faq["из_одних_картинок"] + faq["пустых"] + faq["с_текстом"] == faq["всего"]
    blog = result["блоги"]
    assert blog["выдержек"] + blog["из_одних_картинок"] + blog["с_текстом"] == blog["всего"]


def test_faq_duplicate_that_is_also_image_only_counts_as_duplicate_only(tmp_path):
    """Живой случай (1 запись на боевых данных): дубль без единого слова
    текста. Дубль — не самостоятельный источник вовсе (задача 1), значит
    приоритет у категории "дублей", а не "из одних картинок" — иначе
    сумма разошлась бы с "всего" (запись считалась бы в двух корзинах)."""
    conn = db.connect(tmp_path / "fb2.sqlite")
    db.init_schema(conn)
    _faq_row(conn, "bitrix", 1, "Настоящий ответ.", "Настоящий ответ.")
    _faq_row(conn, "old", 2, "![[assets/x.jpg]]", "", dup_engine="bitrix", dup_nr=1)
    conn.commit()

    result = coverage.faq_blog_coverage(conn)["faq"]
    assert result == {"всего": 2, "дублей": 1, "из_одних_картинок": 0, "пустых": 0, "с_текстом": 1}


def test_citable_sources_excludes_duplicate_excerpt_empty_thread_and_image_only(tmp_path):
    conn = db.connect(tmp_path / "cs.sqlite")
    db.init_schema(conn)
    conn.execute("INSERT INTO threads(tid, fid, title, replies_expected) VALUES (1, 19, 'т1', 0)")
    conn.execute("INSERT INTO posts(mid, tid, page_no, markdown) VALUES (100, 1, 1, 'настоящий текст поста')")
    conn.execute("INSERT INTO threads(tid, fid, title, replies_expected) VALUES (2, 19, 'пустая', NULL)")
    _faq_row(conn, "bitrix", 42, "Ответ.", "Ответ.")
    _faq_row(conn, "old", 7, "Ответ.", "Ответ.", dup_engine="bitrix", dup_nr=42)
    _faq_row(conn, "bitrix", 9, "![[assets/x.jpg]]", "")
    _blog_row(conn, "remont", 5, "Текст.", "Текст.")
    _blog_row(conn, "remont", 6, "Выдержка.", "Выдержка.", is_excerpt=1)
    conn.commit()

    sources = coverage.citable_sources(conn)

    assert sources == ["Тема 1", "FAQ 42", "Блог remont 5"]
    # Дубль FAQ, пустая тема, выдержка блога и запись из одних картинок —
    # ни один не самостоятельный цитируемый источник.
    assert "FAQ старый 7" not in sources
    assert "Тема 2" not in sources
    assert "Блог remont 6" not in sources
    assert "FAQ 9" not in sources


def test_citable_sources_excludes_forum_thread_with_no_quotable_post(tmp_path):
    """Тема с постами, но ни один пост которых не даёт ни одной цитаты
    длиной хотя бы `facts.MIN_QUOTE_CHARS` — структурно то же самое, что
    «из одних картинок» у FAQ/блогов: процитировать физически нечего
    (находка 1 ревью задачи 7, живые примеры — посты «test», «....»)."""
    conn = db.connect(tmp_path / "mute.sqlite")
    db.init_schema(conn)
    conn.execute("INSERT INTO threads(tid, fid, title, replies_expected) VALUES (1, 19, 'немая', 1)")
    conn.execute("INSERT INTO posts(mid, tid, page_no, markdown) VALUES (100, 1, 1, 'test')")
    conn.execute("INSERT INTO posts(mid, tid, page_no, markdown) VALUES (101, 1, 1, '....')")
    conn.execute("INSERT INTO threads(tid, fid, title, replies_expected) VALUES (2, 19, 'живая', 1)")
    conn.execute("INSERT INTO posts(mid, tid, page_no, markdown) VALUES (200, 2, 1, 'настоящий текст поста')")
    conn.commit()

    sources = coverage.citable_sources(conn)

    assert "Тема 1" not in sources
    assert "Тема 2" in sources


def test_citable_sources_boundary_at_min_quote_chars(tmp_path):
    """Граница ровно на `facts.MIN_QUOTE_CHARS` (8): 8 знаков — источник
    остаётся (`>=`, тот же знак, что в `facts.check_one`), 7 — уже "немая"
    тема."""
    conn = db.connect(tmp_path / "mute2.sqlite")
    db.init_schema(conn)
    conn.execute("INSERT INTO threads(tid, fid, title, replies_expected) VALUES (1, 19, 'ровно 8', 1)")
    conn.execute("INSERT INTO posts(mid, tid, page_no, markdown) VALUES (100, 1, 1, '12345678')")
    conn.execute("INSERT INTO threads(tid, fid, title, replies_expected) VALUES (2, 19, 'ровно 7', 1)")
    conn.execute("INSERT INTO posts(mid, tid, page_no, markdown) VALUES (200, 2, 1, '1234567')")
    conn.commit()
    assert facts.MIN_QUOTE_CHARS == 8, "тест держит границу конкретно этого порога"

    sources = coverage.citable_sources(conn)

    assert "Тема 1" in sources
    assert "Тема 2" not in sources


def test_citable_sources_uses_note_body_markdown_not_flat_text_column(tmp_path):
    """Канон дословной проверки — тело заметки (`markdown`, из него строится
    заметка зеркала), не `posts.text` (Global Constraint фазы №1) — они
    расходятся у 56% постов на живом корпусе. Пост с длинным `text`, но
    пустым/коротким `markdown`, всё равно "немой" для этой меры."""
    conn = db.connect(tmp_path / "mute3.sqlite")
    db.init_schema(conn)
    conn.execute("INSERT INTO threads(tid, fid, title, replies_expected) VALUES (1, 19, 'т', 0)")
    conn.execute(
        "INSERT INTO posts(mid, tid, page_no, text, markdown) VALUES (100, 1, 1, "
        "'достаточно длинный плоский текст', 'test')")
    conn.commit()

    assert "Тема 1" not in coverage.citable_sources(conn)


def _article(tmp_path, name, draft, verified, meta):
    from pipeline import articles
    out = tmp_path / name
    out.write_text(articles.render(draft, verified, meta), encoding="utf-8")
    return out


def _fact(fid, source, quote):
    return {"id": fid, "источник": source, "цитата": quote, "суть": "х",
            "автор": "Автор", "дата": "01.01.2020"}


def test_citation_coverage_counts_source_cited_twice_as_one(tmp_path):
    draft = "Раз[^f1]. Два[^f2]."
    verified = [_fact("f1", "Тема 1#Пост 100", "раз"), _fact("f2", "Тема 1#Пост 101", "два")]
    _article(tmp_path, "a.md", draft, verified, {"заголовок": "А"})

    result = coverage.citation_coverage(tmp_path, ["Тема 1", "Тема 2", "FAQ 1"])

    assert result["процитировано"] == 1
    assert result["не процитировано"] == 2
    assert sorted(result["список"]) == ["FAQ 1", "Тема 2"]
    assert result["доля"] == 2 / 3


def test_citation_coverage_counts_source_cited_across_two_articles_once(tmp_path):
    _article(tmp_path, "a.md", "Раз[^f1].", [_fact("f1", "Тема 1#Пост 100", "раз")], {"заголовок": "А"})
    _article(tmp_path, "b.md", "Два[^f1].", [_fact("f1", "Тема 1#Пост 200", "два")], {"заголовок": "Б"})

    result = coverage.citation_coverage(tmp_path, ["Тема 1"])

    assert result["процитировано"] == 1
    assert result["не процитировано"] == 0
    assert result["список"] == []


def test_citation_coverage_uncited_source_lands_in_list(tmp_path):
    result = coverage.citation_coverage(tmp_path, ["Тема 1", "Тема 2"])
    assert result["не процитировано"] == 2
    assert sorted(result["список"]) == ["Тема 1", "Тема 2"]
    assert result["доля"] == 1.0


def test_citation_coverage_deduplicates_repeated_source_in_denominator(tmp_path):
    """`sources` может прийти с повтором (конкатенация нескольких
    запросов) — источник не становится двумя источниками только потому,
    что назван в списке дважды."""
    result = coverage.citation_coverage(tmp_path, ["Тема 1", "Тема 1", "Тема 2"])
    assert result["не процитировано"] == 2
    assert result["список"] == ["Тема 1", "Тема 2"]
    assert result["доля"] == 1.0


def test_citation_coverage_empty_source_list_gives_zero_share_not_error(tmp_path):
    result = coverage.citation_coverage(tmp_path, [])
    assert result == {"процитировано": 0, "не процитировано": 0, "доля": 0.0,
                       "список": [], "не_разобрано": []}


def test_citation_coverage_reports_unparsable_article_files_separately(tmp_path):
    """Файл без корректного frontmatter (находка 4 ревью задачи 7) — не
    молчаливый `continue`: он попадает в "не_разобрано" отдельно, а
    статьи, разобравшиеся нормально, продолжают считаться как обычно."""
    bad = tmp_path / "sub" / "не-статья.md"
    bad.parent.mkdir()
    bad.write_text("нет фронтматтера вовсе\n", encoding="utf-8")
    _article(tmp_path, "ok.md", "Раз[^f1].", [_fact("f1", "Тема 1#Пост 100", "раз")], {"заголовок": "А"})

    result = coverage.citation_coverage(tmp_path, ["Тема 1", "Тема 2"])

    assert result["не_разобрано"] == [str(bad)]
    assert result["процитировано"] == 1
    assert result["не процитировано"] == 1
    assert result["список"] == ["Тема 2"]
