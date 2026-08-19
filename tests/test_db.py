import sqlite3
from pipeline import db

def test_init_schema_creates_tables(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    db.init_schema(conn)
    got = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert {"sections", "threads", "posts", "attachments", "pages"} <= got

def test_posts_fts_searches_russian(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    db.init_schema(conn)
    conn.execute("INSERT INTO threads(tid, fid, title) VALUES (1, 19, 'тест')")
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, html, text) "
                 "VALUES (10, 1, 1, 'DTR', '2007-04-02 12:04:04', '', 'тормозные трубки 4,75 мм')")
    conn.commit()
    rows = list(conn.execute("SELECT mid FROM posts_fts WHERE posts_fts MATCH 'трубки'"))
    assert rows == [(10,)]
