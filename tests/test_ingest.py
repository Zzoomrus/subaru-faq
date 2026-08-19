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


def test_ingest_writes_kind_and_status_from_the_shared_rule(tmp_path):
    # I4/I5: правило «контент против хрома» одно на весь проект
    # (pipeline.attachments), и загрузчик обязан класть его результат в
    # базу — иначе фаза добора либо качает 20 тысяч смайлов, либо молча
    # пропускает 348 своих вложений.
    pages, manifest = _prepare(tmp_path, ["read_19_10045_1.html", "read_20_31559_2.html"])
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    ingest.ingest_all(pages, manifest, conn)
    rows = dict(conn.execute("SELECT kind, COUNT(*) FROM attachments GROUP BY kind"))
    assert rows.get("chrome", 0) > 0, "смайлы форума должны стать kind='chrome'"
    assert rows.get("external_image", 0) > 0
    assert rows.get("local", 0) == 0, "в этих фикстурах контентных вложений нет"
    statuses = dict(conn.execute(
        "SELECT kind, status FROM attachments GROUP BY kind"))
    assert statuses["chrome"] == "skip"
    assert statuses["external_image"] == "pending"


def test_content_local_attachment_is_pending_not_ok(tmp_path):
    # Дефект I4 буквально: getfile/show_file/thumbnails (348 строк на
    # корпусе) стояли со status='ok' при пустом local_path, и естественный
    # запрос фазы добора `WHERE status='pending'` их не видел.
    from pipeline import attachments
    for url in ("/index.php?t=getfile&id=1", "/upload/WEB-002/thumbnails/x.jpg"):
        kind = attachments.classify(url)
        assert kind == "local"
        assert attachments.initial_status(kind) == "pending"


def test_longer_text_wins_on_conflict(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    ingest.upsert_post(conn, mid=1, tid=9, page_no=1, author="a", author_uid=None,
                       posted_at="", number="", html="", markdown="короткий", text="короткий",
                       edited_by=None, edited_at=None)
    ingest.upsert_post(conn, mid=1, tid=9, page_no=1, author="a", author_uid=None,
                       posted_at="", number="", html="", markdown="намного длиннее исходного",
                       text="намного длиннее исходного", edited_by=None, edited_at=None)
    ingest.upsert_post(conn, mid=1, tid=9, page_no=1, author="a", author_uid=None,
                       posted_at="", number="", html="", markdown="снова короткий", text="снова короткий",
                       edited_by=None, edited_at=None)
    text = conn.execute("SELECT text FROM posts WHERE mid = 1").fetchone()[0]
    assert text == "намного длиннее исходного"


def test_ingest_all_is_idempotent_on_rerun(tmp_path):
    # Найдено на реальном корпусе (задача 8): attachments — простой INSERT
    # без ON CONFLICT, повторный ingest_all на тех же файлах удваивал
    # строки (29376 -> 58752). threads/posts/pages уже были идемпотентны
    # через ON CONFLICT/INSERT OR IGNORE/INSERT OR REPLACE — здесь это
    # зафиксировано явно тестом, а не подразумевается.
    pages, manifest = _prepare(tmp_path, ["read_19_10045_1.html", "read_20_31559_2.html"])
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)

    def counts():
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("threads", "posts", "pages", "attachments")}

    ingest.ingest_all(pages, manifest, conn)
    after_first = counts()
    assert after_first["attachments"] > 0, "фикстуры должны содержать хоть одно вложение"

    ingest.ingest_all(pages, manifest, conn)
    after_second = counts()

    assert after_second == after_first


def test_ingest_all_still_ingests_newly_added_pages_after_rerun(tmp_path):
    # Повторный ingest_all не должен просто игнорировать вообще всё —
    # страницы, добавленные в pages_dir после первого прогона (например,
    # добор архива в следующей фазе), должны нормально влиться.
    pages, manifest = _prepare(tmp_path, ["read_19_10045_1.html"])
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    ingest.ingest_all(pages, manifest, conn)
    first_attachments = conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]

    # добавляем вторую страницу прямо в тот же каталог + переписываем manifest
    (pages / "read_20_31559_2.html").write_bytes((FIX / "read_20_31559_2.html").read_bytes())
    names = ["read_19_10045_1.html", "read_20_31559_2.html"]
    manifest.write_text("\n".join(
        json.dumps({"key": n.replace(".html", "").replace("_", "|"), "file": n,
                    "url": "http://subaru-faq.ru/" + n, "ts": "20150419142404"},
                   ensure_ascii=False) for n in names), encoding="utf-8")

    ingest.ingest_all(pages, manifest, conn)
    second_attachments = conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]

    assert second_attachments > first_attachments


def test_ingest_all_rerun_does_not_erase_phase2_attachment_statuses(tmp_path):
    # Требование тимлида: повторный ingest_all не должен терять
    # local_path/status, которые к тому времени успеет проставить фаза
    # добора картинок (следующая фаза). Раз уже виденная страница вообще
    # не заходит в цикл вставки вложений — трогать нечего, строки остаются
    # как есть, включая те, что фаза 2 уже разметила.
    pages, manifest = _prepare(tmp_path, ["read_19_10045_1.html"])
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    ingest.ingest_all(pages, manifest, conn)

    row = conn.execute("SELECT id, mid, url FROM attachments LIMIT 1").fetchone()
    assert row is not None, "фикстура должна содержать хоть одно вложение"
    att_id, mid, url = row
    conn.execute("UPDATE attachments SET local_path = ?, status = 'downloaded' WHERE id = ?",
                 ("wiki/assets/x.jpg", att_id))
    conn.commit()

    ingest.ingest_all(pages, manifest, conn)

    after = conn.execute("SELECT local_path, status FROM attachments WHERE id = ?", (att_id,)).fetchone()
    assert after == ("wiki/assets/x.jpg", "downloaded")


def test_ingest_sections_reads_names(tmp_path):
    pages = tmp_path / "pages"; pages.mkdir()
    (pages / "index_1.html").write_bytes((FIX / "index_1.html").read_bytes())
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    assert ingest.ingest_sections(pages, conn) >= 20
    title = conn.execute("SELECT title FROM sections WHERE fid = 19").fetchone()[0]
    assert "Типовые вопросы" in title


def test_ingest_stores_markdown_body_alongside_plain_text(tmp_path):
    # I1: до этой правки parse_thread считал markdown и выбрасывал его —
    # колонки в схеме не было, а в заметку шёл plain_text, где маркер
    # цитаты снят и цитата чужих слов неотличима от слов автора поста
    # (13775 постов с цитатами на корпусе). markdown нужен телу заметки,
    # text остаётся для полнотекстового поиска и механической проверки
    # цитат в статьях следующей фазы.
    pages, manifest = _prepare(tmp_path, ["read_19_10045_1.html"])
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    ingest.ingest_all(pages, manifest, conn)
    markdown, text = conn.execute(
        "SELECT markdown, text FROM posts WHERE mid = 302230").fetchone()
    assert markdown.startswith("> KOLESO пишет:"), "цитата обязана остаться блокквотом"
    assert text.startswith("KOLESO пишет:"), "text по-прежнему плоский — он для поиска"
    assert "Передаточное отношение" in markdown


def test_longer_text_wins_keeps_markdown_of_the_same_version(tmp_path):
    # Дедуп постов идёт по длине `text`; markdown обязан приезжать из той же
    # версии поста, что и победивший text, иначе тело заметки и её индекс
    # разойдутся.
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    ingest.upsert_post(conn, mid=1, tid=9, page_no=1, author="a", author_uid=None,
                       posted_at="", number="", html="", markdown="> к", text="к",
                       edited_by=None, edited_at=None)
    ingest.upsert_post(conn, mid=1, tid=9, page_no=1, author="a", author_uid=None,
                       posted_at="", number="", html="", markdown="> длинный текст",
                       text="длинный текст", edited_by=None, edited_at=None)
    assert conn.execute("SELECT markdown, text FROM posts WHERE mid = 1").fetchone() == \
        ("> длинный текст", "длинный текст")
