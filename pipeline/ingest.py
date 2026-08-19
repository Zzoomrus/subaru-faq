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
from urllib.parse import urlparse

from pipeline import parse_listing, parse_thread

_PAGE_RE = re.compile(r"^(read|message)_(\d+)_(\d+)_(\d+)\.html$")


def upsert_thread_from_listing(conn, t) -> None:
    """Записывает тему из оглавления. Оглавление — авторитетный источник:
    перезаписывает существующую строку (в т.ч. фолбэк-строку, созданную
    `ensure_thread_from_page`) целиком, порядок вызовов не важен.
    """
    conn.execute(
        "INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views, pages_expected) "
        "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(tid) DO UPDATE SET "
        "fid=excluded.fid, title=excluded.title, author=excluded.author, started_at=excluded.started_at, "
        "replies_expected=excluded.replies_expected, views=excluded.views, "
        "pages_expected=max(threads.pages_expected, excluded.pages_expected)",
        (t.tid, t.fid, t.title, t.author, t.started_at, t.replies, t.views, t.pages))


def ensure_thread_from_page(conn, *, tid, fid, title) -> None:
    """Фолбэк для тем, которых нет ни в одном оглавлении: часть архива
    содержит страницы с постами для тем, отсутствующих во всех собранных
    `list_*.html` (см. отчёт задачи 5 — 1612 таких тем). Без этой функции
    их посты остаются "сиротами", ссылаясь на несуществующий `tid`, а
    зеркало (задача 7, обход `SELECT tid FROM threads`) их вообще не увидит.

    `INSERT OR IGNORE` — если строка уже есть (из оглавления или созданная
    раньше другой страницей той же темы), не трогаем её: данные оглавления
    авторитетнее данных со страницы темы, а между несколькими
    страницами-фолбэками одной темы побеждает первая по порядку обхода.

    `replies_expected` оставляем NULL, а не 0 — NULL значит "неизвестно,
    сколько постов должно быть, темы нет в оглавлении", 0 соврал бы, что
    тема пустая. `author`/`started_at`/`views`/`pages_expected` по той же
    причине тоже NULL — оглавление их не проверить.
    """
    conn.execute(
        "INSERT OR IGNORE INTO threads(tid, fid, title, author, started_at, replies_expected, views, pages_expected) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (tid, fid, title, None, None, None, None, None))


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


def ingest_sections(pages_dir: Path, conn) -> int:
    """Заполняет `sections` названиями разделов форума.

    Основной источник — корневая страница `index_1.html`: там перечислены
    все разделы одной страницей. Фолбэк — навигационная ссылка `PAGE_NAME=list&FID=<fid>`
    на любой странице темы раздела (нужен для разделов, которых по какой-то
    причине не оказалось на корневой странице конкретного снимка архива —
    например, исторически FID 5 не всегда отображался на index_1.html).
    """
    import re
    from bs4 import BeautifulSoup
    names: dict[int, str] = {}
    index = Path(pages_dir) / "index_1.html"
    if index.exists():
        soup = BeautifulSoup(_read(index), "lxml")
        for a in soup.select('a[href*="PAGE_NAME=list"]'):
            m = re.search(r"FID=(\d+)", a.get("href", ""))
            text = a.get_text(" ", strip=True)
            if m and text and len(text) > 2:
                names.setdefault(int(m.group(1)), text)
    for path in sorted(Path(pages_dir).glob("read_*.html")):
        m = re.match(r"read_(\d+)_", path.name)
        if not m:
            continue
        fid = int(m.group(1))
        if fid in names:
            continue
        soup = BeautifulSoup(_read(path), "lxml")
        link = soup.select_one('a[href*="PAGE_NAME=list&FID=%d"]' % fid)
        if link and link.get_text(" ", strip=True):
            names[fid] = link.get_text(" ", strip=True)
    for fid, title in names.items():
        conn.execute("INSERT INTO sections(fid, title) VALUES (?,?) "
                     "ON CONFLICT(fid) DO UPDATE SET title=excluded.title", (fid, title))
    conn.commit()
    return len(names)


def _classify_attachment(url: str) -> str:
    """`local`, если адрес не указывает на чужой хост, иначе `external_image`.

    Прежняя эвристика (`"subaru-faq" in url or url.startswith("/")`) не
    распознавала относительный путь без ведущего слэша
    (`images/smiley_icons/icon_smile.gif`) — тот же смайл форума, что при
    пути `/bitrix/images/...` считался бы `local`. На корпусе это 2110
    вложений, ушедших в `external_image`. Смысл правила: локальный — это
    любой адрес, у которого нет собственного хоста (`urlparse(...).netloc`
    пуст — относительный путь, с ведущим слэшем или без) плюс адреса самого
    форума; внешний — `http(s)://` или протокол-относительный (`//host/...`)
    адрес любого другого хоста. `urlparse("//host/x").netloc` возвращает
    хост и без явной схемы, так что оба края (`http://`/`https://` и
    `//host/...`) проверяются одинаково через `netloc`.
    """
    netloc = urlparse(url).netloc
    if not netloc or "subaru-faq" in netloc:
        return "local"
    return "external_image"


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
    stats = {"threads": 0, "posts": 0, "pages": 0, "attachments": 0, "skipped_files": 0}
    prov = _load_manifest(manifest)

    for path in sorted(Path(pages_dir).glob("list_*.html")):
        for t in parse_listing.parse(_read(path)):
            upsert_thread_from_listing(conn, t)
            stats["threads"] += 1

    for path in sorted(Path(pages_dir).glob("*.html")):
        m = _PAGE_RE.match(path.name)
        if not m:
            # list_*.html (уже обработаны в цикле выше) и index_*.html —
            # не страницы тем, это не "пропуск", а другая категория файлов,
            # в счётчик skipped_files не входят.
            #
            # read_*/message_* с именем, не совпавшим с _PAGE_RE, — это
            # настоящие пропуски: считаем в skipped_files. На реальном
            # корпусе таких ровно два, оба — подтверждённые эмпирически
            # дубли корректно поименованных файлов (см. отчёт задачи 5,
            # раздел «пропущенные файлы»): read_23_23771<br_1.html (`<br`
            # внутри сегмента TID) и message_7_68277_unread_mid.html (текст
            # вместо MID в последнем сегменте). Пропуск не теряет ни одного
            # поста — контент дублируется в файлах с корректными именами.
            if path.name.startswith("read_") or path.name.startswith("message_"):
                stats["skipped_files"] += 1
            continue
        kind, fid, tid, tail = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        page_no = tail if kind == "read" else 1
        page = parse_thread.parse(_read(path))
        if page.posts:
            # Фолбэк создаём только когда страница реально дала хотя бы один
            # пост. Часть страниц (см. отчёт задачи 5) — сбойные снимки без
            # единого forum-post-text (спам-темы вроде "adidas Tubular
            # Radial...", MID=0 в имени файла): у них нет никакого реального
            # контента, и заводить для них строку threads означало бы
            # протащить спам-заголовок в базу знаний зеркала (задача 7).
            ensure_thread_from_page(conn, tid=tid, fid=fid, title=page.title)
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
                kind_a = _classify_attachment(url)
                conn.execute(
                    "INSERT INTO attachments(mid, kind, url, local_path, status) VALUES (?,?,?,?,?)",
                    (p.mid, kind_a, url, None, "ok" if kind_a == "local" else "pending"))
                stats["attachments"] += 1
    conn.commit()
    return stats
