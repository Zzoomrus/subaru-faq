"""Загрузка разобранных страниц архива в SQLite.

Обходит `list_*.html` (оглавления разделов) и `read_*.html`/`message_*.html`
(страницы тем), пишет темы/посты/страницы/вложения в базу, созданную
`pipeline.db`.

Дедуп постов — по `mid`: один и тот же пост может встретиться и на
`read`-странице, и на `message`-странице (archive содержит обе формы для
пересекающегося множества тем), а также в задублированных файлах архива
(одна тема сохранена дважды под разными FID). Побеждает версия с более
длинным `text` — короткие/обрезанные варианты не должны затирать полные
(`upsert_post`).

Имя файла даёт `page_no` только для `read_*` (последний сегмент —
реальный номер страницы темы). Для `message_*` последний сегмент не
всегда является MID (в части файлов там номер страницы) и никогда не
использовался бы как `page_no` для многостраничных тем — но каждая
`message_*`-страница уже отдаёт единственный плоский снимок темы, поэтому
`page_no` для всех её постов фиксирован в 1. Настоящий `mid` каждого поста
всегда берётся из атрибута `id="messageNNN"` разобранной таблицы
(`Post.mid`), а не из имени файла.
"""
import json
import re
from pathlib import Path

from pipeline import parse_listing, parse_thread

_PAGE_RE = re.compile(r"^(read|message)_(\d+)_(\d+)_(\d+)\.html$")


def upsert_post(conn, *, mid, tid, page_no, author, author_uid, posted_at,
                 number, html, text, edited_by, edited_at) -> None:
    row = conn.execute("SELECT text FROM posts WHERE mid = ?", (mid,)).fetchone()
    if row is not None and len(row[0] or "") >= len(text or ""):
        return
    conn.execute(
        "INSERT INTO posts(mid, tid, page_no, author, author_uid, posted_at, number, html, text, edited_by, edited_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(mid) DO UPDATE SET "
        "tid=excluded.tid, page_no=excluded.page_no, author=excluded.author, author_uid=excluded.author_uid, "
        "posted_at=excluded.posted_at, number=excluded.number, html=excluded.html, text=excluded.text, "
        "edited_by=excluded.edited_by, edited_at=excluded.edited_at",
        (mid, tid, page_no, author, author_uid, posted_at, number, html, text, edited_by, edited_at))


def _read(path: Path) -> str:
    return path.read_bytes().decode("cp1251", "replace")


def _load_manifest(manifest: Path) -> dict:
    prov = {}
    if Path(manifest).exists():
        for line in Path(manifest).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("file"):
                    prov[rec["file"]] = rec
    return prov


def ingest_all(pages_dir: Path, manifest: Path, conn) -> dict[str, int]:
    stats = {"threads": 0, "posts": 0, "pages": 0, "attachments": 0}
    prov = _load_manifest(manifest)

    for path in sorted(Path(pages_dir).glob("list_*.html")):
        for t in parse_listing.parse(_read(path)):
            conn.execute(
                "INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views, pages_expected) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(tid) DO UPDATE SET "
                "fid=excluded.fid, title=excluded.title, author=excluded.author, started_at=excluded.started_at, "
                "replies_expected=excluded.replies_expected, views=excluded.views, "
                "pages_expected=max(threads.pages_expected, excluded.pages_expected)",
                (t.tid, t.fid, t.title, t.author, t.started_at, t.replies, t.views, t.pages))
            stats["threads"] += 1

    for path in sorted(Path(pages_dir).glob("*.html")):
        m = _PAGE_RE.match(path.name)
        if not m:
            # Не совпадает по формату имени: index_*.html, list_*.html (уже
            # обработаны выше), message_bot_challenge.html (без числовых
            # сегментов) и файл со сломанным именем
            # read_23_23771<br_1.html (обёрнут `<br` внутри сегмента TID) —
            # его содержимое дублирует корректно именованный
            # read_23_23771_1.html, который обходом каталога тоже найдётся
            # и разберётся штатно, так что пропуск этого файла не теряет
            # ни одного поста.
            continue
        kind, fid, tid, tail = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        page_no = tail if kind == "read" else 1
        page = parse_thread.parse(_read(path))
        rec = prov.get(path.name, {})
        conn.execute(
            "INSERT OR REPLACE INTO pages(key, file, url, snapshot_ts, tid, page_no) VALUES (?,?,?,?,?,?)",
            (rec.get("key", path.stem), path.name, rec.get("url", ""), rec.get("ts", ""), tid, page_no))
        stats["pages"] += 1
        for p in page.posts:
            upsert_post(conn, mid=p.mid, tid=tid, page_no=page_no, author=p.author,
                        author_uid=p.author_uid, posted_at=p.posted_at, number=p.number,
                        html=p.html, text=p.text, edited_by=p.edited_by, edited_at=p.edited_at)
            stats["posts"] += 1
            for url in p.images:
                kind_a = "local" if "subaru-faq" in url or url.startswith("/") else "external_image"
                conn.execute(
                    "INSERT INTO attachments(mid, kind, url, local_path, status) VALUES (?,?,?,?,?)",
                    (p.mid, kind_a, url, None, "ok" if kind_a == "local" else "pending"))
                stats["attachments"] += 1
    conn.commit()
    return stats
