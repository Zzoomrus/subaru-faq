"""Поиск по трём источникам: плоский текст + FTS у FAQ и блогов.

Дефект I1 итогового ревью Ф2: `posts` имели `text` и `posts_fts`, а `faq` и
`blog_posts` — только markdown, то есть главная механика Ф3 (найти фразу ->
сослаться -> сверить дословность) была применима к одному источнику из трёх.

Здесь же зафиксировано и разделение обязанностей, чтобы его не потеряли:
плоский текст — ДЛЯ ПОИСКА, канон дословной сверки — тело заметки
(Ruling 30, `docs/контракт-зеркала.md`).
"""
from pipeline import db, html_text, parse_blog, parse_faq


def _conn(tmp_path):
    conn = db.connect(tmp_path / "s.sqlite")
    db.init_schema(conn)
    return conn


def _seed(conn):
    conn.execute(
        "INSERT INTO faq(engine, nr, question, answer_md, answer_text) VALUES "
        "('bitrix', 502, 'Как менять тормозные колодки?', "
        "'> Nikon писал(а):\\n> старый вопрос\\n\\nСнимаем [суппорт](http://x/s.html) и меняем.', ?)",
        (html_text.plain_text_from_markdown(
            "> Nikon писал(а):\n> старый вопрос\n\nСнимаем [суппорт](http://x/s.html) и меняем."),))
    conn.execute(
        "INSERT INTO blog_posts(blog, post_id, title, body_md, body_text) VALUES "
        "('remont', 184, 'Передние тормоза. Переборка.', "
        "'Разбираем ![](http://x/1.jpg) суппорт полностью.', ?)",
        (html_text.plain_text_from_markdown("Разбираем ![](http://x/1.jpg) суппорт полностью."),))
    conn.commit()
    return db.rebuild_search_index(conn)


def test_flat_text_drops_markup_but_keeps_quoted_words(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn)
    answer_md, answer_text = conn.execute(
        "SELECT answer_md, answer_text FROM faq WHERE nr = 502").fetchone()
    assert "> Nikon" in answer_md and "](http://x/s.html)" in answer_md
    assert "> " not in answer_text and "http://x/s.html" not in answer_text
    # Содержимое цитаты не теряется — снят только маркер (см.
    # html_text.plain_text_from_markdown).
    assert "Nikon писал(а):" in answer_text and "суппорт" in answer_text
    body_md, body_text = conn.execute(
        "SELECT body_md, body_text FROM blog_posts WHERE post_id = 184").fetchone()
    assert "![](" in body_md and "![](" not in body_text


def test_search_finds_a_phrase_in_all_three_sources(tmp_path):
    conn = _conn(tmp_path)
    conn.execute("INSERT INTO posts(mid, tid, page_no, text, markdown) VALUES "
                 "(1, 1, 1, 'Суппорт форума разобран', 'Суппорт форума разобран')")
    counts = _seed(conn)
    assert counts == {"faq_fts": 1, "blog_fts": 1}
    assert conn.execute("SELECT mid FROM posts_fts WHERE posts_fts MATCH 'суппорт'").fetchall() == [(1,)]
    assert conn.execute(
        "SELECT engine, nr FROM faq_fts WHERE faq_fts MATCH 'суппорт'").fetchall() == [("bitrix", 502)]
    assert conn.execute(
        "SELECT blog, post_id FROM blog_fts WHERE blog_fts MATCH 'суппорт'").fetchall() == [("remont", 184)]


def test_search_can_be_narrowed_to_the_question_or_the_title(tmp_path):
    # Вопрос FAQ и название записи блога — отдельные колонки индекса: искать
    # по формулировке вопроса Ф3 будет не реже, чем по телу ответа.
    conn = _conn(tmp_path)
    _seed(conn)
    assert conn.execute("SELECT nr FROM faq_fts WHERE faq_fts MATCH 'question: колодки'").fetchall() == [(502,)]
    assert conn.execute("SELECT nr FROM faq_fts WHERE faq_fts MATCH 'answer: колодки'").fetchall() == []
    assert conn.execute("SELECT post_id FROM blog_fts WHERE blog_fts MATCH 'title: переборка'").fetchall() == [(184,)]


def test_rebuild_is_idempotent_and_follows_deletions(tmp_path):
    # Индекс наполняется целиком, а не триггерами — значит он не может
    # разойтись с источником; разошедшийся индекс молча отдавал бы «фразы
    # нет» на тексте, где она есть.
    conn = _conn(tmp_path)
    _seed(conn)
    assert db.rebuild_search_index(conn) == {"faq_fts": 1, "blog_fts": 1}
    conn.execute("DELETE FROM faq WHERE nr = 502")
    conn.commit()
    assert db.rebuild_search_index(conn) == {"faq_fts": 0, "blog_fts": 1}
    assert conn.execute("SELECT count(*) FROM faq_fts WHERE faq_fts MATCH 'суппорт'").fetchone()[0] == 0


def test_loaders_leave_the_index_in_sync(tmp_path, monkeypatch):
    # Тот же контракт на уровне команды: после `load_all` индекс совпадает с
    # таблицей, даже если страниц не нашлось вовсе (пустой манифест).
    conn = _conn(tmp_path)
    stats_faq = parse_faq.load_all(tmp_path / "нет", tmp_path / "нет.jsonl", conn)
    stats_blog = parse_blog.load_all(tmp_path / "нет", tmp_path / "нет.jsonl", conn)
    assert stats_faq["faq_fts"] == 0 and stats_faq["blog_fts"] == 0
    assert stats_blog["faq_fts"] == 0 and stats_blog["blog_fts"] == 0
