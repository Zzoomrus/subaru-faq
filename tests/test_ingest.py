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
