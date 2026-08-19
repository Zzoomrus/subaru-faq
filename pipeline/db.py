import sqlite3
from pathlib import Path

# `posts` хранит тело поста в трёх видах, и это намеренно:
#   html     — исходный фрагмент `div.forum-post-text`, из него в любой
#              момент можно пере-отрендерить всё остальное без пере-краулинга;
#   markdown — то, что читает человек в заметке зеркала: цитаты остаются
#              блокквотами, ссылки — ссылками с адресом (дефект I1 ревью:
#              раньше эта колонка не существовала вовсе, и в заметку шёл
#              plain_text, где цитата чужих слов неотличима от слов автора);
#   text     — плоский текст для полнотекстового поиска (`posts_fts` строится
#              именно по нему) и для механической проверки дословных цитат
#              в статьях следующей фазы.
SCHEMA = """
CREATE TABLE IF NOT EXISTS sections (
    fid INTEGER PRIMARY KEY, title TEXT);
CREATE TABLE IF NOT EXISTS threads (
    tid INTEGER PRIMARY KEY, fid INTEGER, title TEXT, author TEXT,
    started_at TEXT, replies_expected INTEGER, views INTEGER, pages_expected INTEGER);
CREATE TABLE IF NOT EXISTS posts (
    mid INTEGER PRIMARY KEY, tid INTEGER, page_no INTEGER, author TEXT, author_uid INTEGER,
    posted_at TEXT, number TEXT, html TEXT, markdown TEXT, text TEXT,
    edited_by TEXT, edited_at TEXT);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mid INTEGER, kind TEXT, url TEXT,
    local_path TEXT, status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS pages (
    key TEXT PRIMARY KEY, file TEXT, url TEXT, snapshot_ts TEXT, tid INTEGER, page_no INTEGER);
CREATE INDEX IF NOT EXISTS idx_posts_tid ON posts(tid);
CREATE INDEX IF NOT EXISTS idx_attach_mid ON attachments(mid);
CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    text, mid UNINDEXED, content='posts', content_rowid='mid');
CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
    INSERT INTO posts_fts(rowid, text) VALUES (new.mid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, text) VALUES('delete', old.mid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS posts_au AFTER UPDATE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, text) VALUES('delete', old.mid, old.text);
    INSERT INTO posts_fts(rowid, text) VALUES (new.mid, new.text);
END;
"""

def connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
