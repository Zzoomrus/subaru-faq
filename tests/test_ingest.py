import json
from pathlib import Path
from pipeline import db, ingest

FIX = Path(__file__).parent / "fixtures"

def _prepare(tmp_path, names):
    pages = tmp_path / "pages"
    pages.mkdir()
    for n in names:
        (pages / n).write_bytes((FIX / n).read_bytes())
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("\n".join(
        json.dumps({"key": n.replace(".html", "").replace("_", "|"), "file": n,
                    "url": "http://subaru-faq.ru/" + n, "ts": "20150419142404"},
                   ensure_ascii=False) for n in names), encoding="utf-8")
    return pages, manifest

def test_ingest_counts_and_dedups(tmp_path):
    pages, manifest = _prepare(tmp_path, ["read_19_10045_1.html", "read_20_31559_2.html"])
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    stats = ingest.ingest_all(pages, manifest, conn)
    assert stats["posts"] > 0
    dupes = list(conn.execute("SELECT mid, COUNT(*) c FROM posts GROUP BY mid HAVING c > 1"))
    assert dupes == []

def test_orphan_thread_gets_created_and_posts_not_orphaned(tmp_path):
    # read_19_10045_1.html без единого list_*.html: тема нигде не встречается
    # в оглавлениях, но страница с постами есть.
    pages, manifest = _prepare(tmp_path, ["read_19_10045_1.html"])
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    ingest.ingest_all(pages, manifest, conn)
    row = conn.execute(
        "SELECT fid, title, replies_expected FROM threads WHERE tid = 10045"
    ).fetchone()
    assert row is not None, "тема без оглавления должна получить строку в threads"
    fid, title, replies_expected = row
    assert fid == 19
    assert title == "Параметры коробок и редукторов Субару"
    assert replies_expected is None, "NULL — 'неизвестно', а не 0 ('пусто')"
    orphans = conn.execute(
        "SELECT COUNT(*) FROM posts p LEFT JOIN threads t USING(tid) WHERE t.tid IS NULL"
    ).fetchone()[0]
    assert orphans == 0


def test_listing_data_wins_over_page_fallback_regardless_of_order(tmp_path):
    from pipeline.parse_listing import ThreadMeta
    t = ThreadMeta(tid=1, fid=19, title="Настоящее название", author="Настоящий автор",
                   started_at="2007-04-02", replies=50, views=90730, pages=3, last_mid=None)
    cols = "fid, title, author, started_at, replies_expected, views"

    # порядок A: сначала страница темы (без оглавления), потом оглавление —
    # оглавление должно перезаписать фолбэк своими данными.
    conn = db.connect(tmp_path / "a.sqlite"); db.init_schema(conn)
    ingest.ensure_thread_from_page(conn, tid=1, fid=99, title="Название со страницы")
    ingest.upsert_thread_from_listing(conn, t)
    assert conn.execute(f"SELECT {cols} FROM threads WHERE tid=1").fetchone() == \
        (19, "Настоящее название", "Настоящий автор", "2007-04-02", 50, 90730)

    # порядок B: сначала оглавление, потом страница темы — фолбэк не должен
    # затереть уже имеющиеся данные оглавления.
    conn2 = db.connect(tmp_path / "b.sqlite"); db.init_schema(conn2)
    ingest.upsert_thread_from_listing(conn2, t)
    ingest.ensure_thread_from_page(conn2, tid=1, fid=99, title="Название со страницы")
    assert conn2.execute(f"SELECT {cols} FROM threads WHERE tid=1").fetchone() == \
        (19, "Настоящее название", "Настоящий автор", "2007-04-02", 50, 90730)


def test_classify_attachment_relative_path_without_leading_slash_is_local():
    # Смайлы форума (`images/smiley_icons/icon_smile.gif`) — относительный
    # путь без ведущего слэша, но это точно тот же хост, что и `/bitrix/...`.
    assert ingest._classify_attachment("images/smiley_icons/icon_smile.gif") == "local"
    assert ingest._classify_attachment("/bitrix/images/smiley_icons/icon_smile.gif") == "local"
    # Настоящий внешний хост остаётся external_image.
    assert ingest._classify_attachment("http://s017.radikal.ru/i430/x.jpg") == "external_image"
    # Протокол-относительный адрес — это тоже другой хост, не локальный путь.
    assert ingest._classify_attachment("//i57.fastpic.ru/big/x.jpg") == "external_image"


def test_longer_text_wins_on_conflict(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    ingest.upsert_post(conn, mid=1, tid=9, page_no=1, author="a", author_uid=None,
                       posted_at="", number="", html="", text="короткий", edited_by=None, edited_at=None)
    ingest.upsert_post(conn, mid=1, tid=9, page_no=1, author="a", author_uid=None,
                       posted_at="", number="", html="", text="намного длиннее исходного", edited_by=None, edited_at=None)
    ingest.upsert_post(conn, mid=1, tid=9, page_no=1, author="a", author_uid=None,
                       posted_at="", number="", html="", text="снова короткий", edited_by=None, edited_at=None)
    text = conn.execute("SELECT text FROM posts WHERE mid = 1").fetchone()[0]
    assert text == "намного длиннее исходного"


def test_ingest_sections_reads_names(tmp_path):
    pages = tmp_path / "pages"; pages.mkdir()
    (pages / "index_1.html").write_bytes((FIX / "index_1.html").read_bytes())
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    assert ingest.ingest_sections(pages, conn) >= 20
    title = conn.execute("SELECT title FROM sections WHERE fid = 19").fetchone()[0]
    assert "Типовые вопросы" in title
