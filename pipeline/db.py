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
-- FAQ (Ф2, задача 6): раздел архивирован ДВУМЯ движками разом (см. отчёт
-- задачи 5) — современным Bitrix (`ELEMENT_ID`) и старым самописным
-- (`nr`/`catnr`/`prog`). Их номера — НЕЗАВИСИМЫЕ пространства имён, которые
-- на живом корпусе реально пересекаются (17 из 177 файлов, разный контент
-- под одним числом — см. task-6-report.md), поэтому первичный ключ таблицы
-- составной (engine, nr), а не просто nr. `catnr` осмыслен только для
-- старого движка (Bitrix-адрес его не несёт) — сознательное отклонение от
-- брифа (тот писан до открытия двух движков в задаче 5).
CREATE TABLE IF NOT EXISTS faq (
    engine TEXT, nr INTEGER, catnr INTEGER, prog TEXT, category TEXT,
    question TEXT, answer_md TEXT, source_url TEXT, snapshot_ts TEXT,
    PRIMARY KEY (engine, nr));
CREATE TABLE IF NOT EXISTS faq_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT, engine TEXT, nr INTEGER, url TEXT, local_path TEXT);
CREATE INDEX IF NOT EXISTS idx_faq_images_entry ON faq_images(engine, nr);
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
