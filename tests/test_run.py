import json
import sqlite3
from pathlib import Path

from pipeline import run

FIX = Path(__file__).parent / "fixtures"
NAMES = ["read_19_10045_1.html", "read_20_31559_2.html", "index_1.html"]


def _archive(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    for n in NAMES:
        (pages / n).write_bytes((FIX / n).read_bytes())
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("\n".join(
        json.dumps({"key": n, "file": n, "url": "http://subaru-faq.ru/" + n,
                    "ts": "20150419142404"}) for n in NAMES), encoding="utf-8")
    return pages, manifest


def _args(tmp_path, *cmd):
    pages, manifest = _archive(tmp_path)
    return [*cmd, "--pages", str(pages), "--manifest", str(manifest),
            "--db", str(tmp_path / "forum.sqlite"),
            "--csv", str(tmp_path / "coverage.csv"),
            "--wiki", str(tmp_path / "wiki"),
            "--mirror-dir", "Источники",
            # Изолируем от реального `data/assets/` репозитория (задача 8):
            # без этого `ingest`/`all`/`mirror` подхватили бы дефолтный
            # боевой манифест/каталог добора Ф2 относительно cwd теста.
            "--assets-manifest", str(tmp_path / "assets-manifest.jsonl"),
            "--assets-root", str(tmp_path / "assets"),
            # То же самое для третьего источника (руководство automn.ru):
            # дефолт `data/automn` — реальный боевой каталог добора в 805+
            # страниц, без изоляции `all`/`mirror` молча подмешал бы его в
            # каждый тест этого файла.
            "--automn-root", str(tmp_path / "automn-none")]


def _faq_site(tmp_path):
    # Одна реальная страница FAQ (nr=10, движок Bitrix, без дублирующих
    # меток) — минимальный, но настоящий сырой снимок, а не synthетика.
    site_root = tmp_path / "site"
    faq_dir = site_root / "faq"
    faq_dir.mkdir(parents=True)
    raw = (FIX / "faq_element_bitrix.html").read_bytes()
    (faq_dir / "10.html").write_bytes(raw)
    manifest = tmp_path / "manifest-site.jsonl"
    from pipeline import assets_state
    assets_state.record(manifest, "http://www.subaru-faq.ru/faq/index.php?ELEMENT_ID=10",
                         "faq/10.html", "ok")
    return site_root, manifest


def _args_with_faq(tmp_path, *cmd):
    site_root, site_manifest = _faq_site(tmp_path)
    return _args(tmp_path, *cmd) + ["--site-root", str(site_root), "--site-manifest", str(site_manifest)]


_BLOG_POST_URL = "http://www.subaru-faq.ru:80/blogs/index.php?page=post&blog=a-detal&post_id=304"


def _blog_site(tmp_path):
    # Одна реальная страница блога (a-detal/304, движок Bitrix, без тегов и
    # комментариев) — минимальный, но настоящий сырой снимок (задача 7).
    site_root = tmp_path / "site"
    blogs_dir = site_root / "blogs"
    blogs_dir.mkdir(parents=True)
    raw = (FIX / "blog_post_simple.html").read_bytes()
    (blogs_dir / "304.html").write_bytes(raw)
    manifest = tmp_path / "manifest-site.jsonl"
    from pipeline import assets_state
    assets_state.record(manifest, _BLOG_POST_URL, "blogs/304.html", "ok")
    return site_root, manifest


def _args_with_blog(tmp_path, *cmd):
    site_root, site_manifest = _blog_site(tmp_path)
    return _args(tmp_path, *cmd) + ["--site-root", str(site_root), "--site-manifest", str(site_manifest)]


def test_all_runs_the_whole_pipeline(tmp_path):
    # Единственная точка входа: следующая фаза состоит из повторных прогонов,
    # heredoc в документе для этого не годится.
    assert run.main(_args(tmp_path, "all")) == 0
    assert (tmp_path / "forum.sqlite").exists()
    assert (tmp_path / "coverage.csv").exists()
    assert (tmp_path / "wiki" / "Источники" / "Тема 10045.md").exists()


def test_all_includes_faq_notes_alongside_the_forum(tmp_path):
    # Ревизия задачи 6: FAQ обязан собираться ВНУТРИ обычного `all`, а не
    # только ручным вызовом — иначе полный прогон с нуля молча даёт вики
    # без раздела FAQ.
    assert run.main(_args_with_faq(tmp_path, "all")) == 0
    assert (tmp_path / "wiki" / "Источники" / "Тема 10045.md").exists()
    assert (tmp_path / "wiki" / "Источники" / "FAQ" / "FAQ 10.md").exists()


def test_faq_command_loads_and_mirrors_without_touching_the_forum(tmp_path):
    # Отдельная команда — для точечной перегенерации FAQ (правка парсера)
    # без полного форумного `ingest`.
    site_root, site_manifest = _faq_site(tmp_path)
    args = ["faq", "--db", str(tmp_path / "forum.sqlite"),
            "--site-root", str(site_root), "--site-manifest", str(site_manifest),
            "--wiki", str(tmp_path / "wiki"), "--mirror-dir", "Источники"]
    assert run.main(args) == 0
    conn = sqlite3.connect(tmp_path / "forum.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM faq").fetchone()[0] == 1
    assert (tmp_path / "wiki" / "Источники" / "FAQ" / "FAQ 10.md").exists()
    # Форумные таблицы существуют (общая схема), но пустые — ingest не звался.
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0


def test_faq_command_load_only_then_mirror_only(tmp_path):
    site_root, site_manifest = _faq_site(tmp_path)
    common = ["--db", str(tmp_path / "forum.sqlite"),
              "--site-root", str(site_root), "--site-manifest", str(site_manifest),
              "--wiki", str(tmp_path / "wiki"), "--mirror-dir", "Источники"]
    assert run.main(["faq", "load", *common]) == 0
    assert not (tmp_path / "wiki").exists()  # mirror ещё не звался
    assert run.main(["faq", "mirror", *common]) == 0
    assert (tmp_path / "wiki" / "Источники" / "FAQ" / "FAQ 10.md").exists()


def test_faq_command_rejects_unknown_sub_action(tmp_path, capsys):
    rc = run.main(["faq", "index", "--db", str(tmp_path / "forum.sqlite")])
    assert rc == 2
    assert "faq load" in capsys.readouterr().out


def test_faq_mirror_alone_uses_the_shared_assets_directory(tmp_path):
    """Точечный `faq mirror` (без блогов/форума) обязан класть картинки в
    ОБЩИЙ каталог `<mirror-dir>/assets` (задача 2 Ф3, Ruling 37), а не
    заводить свой `FAQ/assets` — иначе следующий полный `all` разложил бы ту
    же картинку по двум местам снова.

    Регрессия ревью: формула этого пути была продублирована инлайном в
    команде `faq` отдельно от `build_mirror` — откат передачи `assets_dir`
    здесь молча не ловился ничем (все 336 тестов оставались зелёными),
    потому что до правки ни один тест не гонял точечную команду с реальной
    картинкой на диске.
    """
    from pipeline import db as _db
    db_path = tmp_path / "forum.sqlite"
    conn = _db.connect(db_path)
    _db.init_schema(conn)
    url = "http://subaru-faq.ru/upload/blog/84b/x.jpg"  # тот же файл, что и FIX_ASSETS ниже
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md) VALUES "
                 "('bitrix', 1, 'вопрос', 'ответ ![](%s)')" % url)
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES ('bitrix', 1, ?)", (url,))
    conn.commit()
    conn.close()

    fix_assets = Path(__file__).parent / "fixtures" / "faq_assets"
    rc = run.main(["faq", "mirror", "--db", str(db_path),
                   "--wiki", str(tmp_path / "wiki"), "--mirror-dir", "Источники",
                   "--archive-assets-manifest", str(fix_assets / "manifest-assets.jsonl"),
                   "--archive-assets-root", str(fix_assets / "assets")])
    assert rc == 0
    mirror_root = tmp_path / "wiki" / "Источники"
    assert not (mirror_root / "FAQ" / "assets").exists()
    assert (mirror_root / "assets").is_dir()
    assert list((mirror_root / "assets").iterdir())


def test_blog_mirror_alone_uses_the_shared_assets_directory(tmp_path):
    """Тот же регрессионный тест, что и у FAQ выше, для команды `blog
    mirror`: без него откат `assets_dir` в этой ветке `main()` тоже не
    ловился ничем.
    """
    from pipeline import db as _db
    db_path = tmp_path / "forum.sqlite"
    conn = _db.connect(db_path)
    _db.init_schema(conn)
    url = "http://subaru-faq.ru/upload/blog/84b/x.jpg"
    conn.execute("INSERT INTO blog_posts(blog, post_id, title, body_md, tags, is_excerpt, truncated) "
                 "VALUES ('remont', 1, 'запись', 'тело ![](%s)', '[]', 0, 0)" % url)
    conn.execute("INSERT INTO blog_images(blog, post_id, comment_id, url) VALUES ('remont', 1, NULL, ?)",
                 (url,))
    conn.commit()
    conn.close()

    fix_assets = Path(__file__).parent / "fixtures" / "faq_assets"
    rc = run.main(["blog", "mirror", "--db", str(db_path),
                   "--wiki", str(tmp_path / "wiki"), "--mirror-dir", "Источники",
                   "--archive-assets-manifest", str(fix_assets / "manifest-assets.jsonl"),
                   "--archive-assets-root", str(fix_assets / "assets")])
    assert rc == 0
    mirror_root = tmp_path / "wiki" / "Источники"
    assert not (mirror_root / "Блоги" / "assets").exists()
    assert (mirror_root / "assets").is_dir()
    assert list((mirror_root / "assets").iterdir())


def test_rebuild_from_scratch_reproduces_faq_table_and_column(tmp_path):
    # Требование лида (ревизия задачи 6): полная пересборка — главная
    # гарантия проекта, она должна восстанавливать FAQ (таблицу И колонку
    # `title`) с нуля, а не только через ручной `ALTER TABLE` на живой базе.
    args = _args_with_faq(tmp_path, "all", "--rebuild")
    assert run.main(args) == 0
    db_path = tmp_path / "forum.sqlite"
    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(faq)").fetchall()}
    assert "title" in cols
    assert conn.execute("SELECT COUNT(*) FROM faq").fetchone()[0] == 1
    conn.close()

    # Второй проход с --rebuild — тот самый "снёс и собрал заново": FAQ
    # переживает пересборку так же, как форумные таблицы.
    assert run.main(args) == 0
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM faq").fetchone()[0] == 1
    conn.close()
    assert (tmp_path / "wiki" / "Источники" / "FAQ" / "FAQ 10.md").exists()


def test_all_includes_blog_notes_alongside_the_forum(tmp_path):
    # Задача 7, тот же принцип, что ревизия задачи 6 закрепила для FAQ:
    # блоги обязаны собираться ВНУТРИ обычного `all`, иначе полный прогон с
    # нуля молча даёт вики без раздела блогов.
    assert run.main(_args_with_blog(tmp_path, "all")) == 0
    assert (tmp_path / "wiki" / "Источники" / "Тема 10045.md").exists()
    assert (tmp_path / "wiki" / "Источники" / "Блоги" / "Блог a-detal 304.md").exists()


def test_blog_command_loads_and_mirrors_without_touching_the_forum(tmp_path):
    site_root, site_manifest = _blog_site(tmp_path)
    args = ["blog", "--db", str(tmp_path / "forum.sqlite"),
            "--site-root", str(site_root), "--site-manifest", str(site_manifest),
            "--wiki", str(tmp_path / "wiki"), "--mirror-dir", "Источники"]
    assert run.main(args) == 0
    conn = sqlite3.connect(tmp_path / "forum.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM blog_posts").fetchone()[0] == 1
    assert (tmp_path / "wiki" / "Источники" / "Блоги" / "Блог a-detal 304.md").exists()
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
    # declared_comments — счётчик со страницы сохраняется в базу для
    # диагностики (ненадёжен, см. task-7-report.md), но реально сохраняется,
    # а не только упоминается в отчёте.
    assert conn.execute("SELECT declared_comments FROM blog_posts").fetchone()[0] == 0


def test_blog_command_load_only_then_mirror_only(tmp_path):
    site_root, site_manifest = _blog_site(tmp_path)
    common = ["--db", str(tmp_path / "forum.sqlite"),
              "--site-root", str(site_root), "--site-manifest", str(site_manifest),
              "--wiki", str(tmp_path / "wiki"), "--mirror-dir", "Источники"]
    assert run.main(["blog", "load", *common]) == 0
    assert not (tmp_path / "wiki").exists()
    assert run.main(["blog", "mirror", *common]) == 0
    assert (tmp_path / "wiki" / "Источники" / "Блоги" / "Блог a-detal 304.md").exists()


def test_blog_command_rejects_unknown_sub_action(tmp_path, capsys):
    rc = run.main(["blog", "index", "--db", str(tmp_path / "forum.sqlite")])
    assert rc == 2
    assert "blog load" in capsys.readouterr().out


def test_rebuild_from_scratch_reproduces_blog_tables(tmp_path):
    # То же требование, что и у FAQ: полная пересборка обязана восстановить
    # схему блогов (таблицы) с нуля, а не через ручной ALTER TABLE.
    args = _args_with_blog(tmp_path, "all", "--rebuild")
    assert run.main(args) == 0
    db_path = tmp_path / "forum.sqlite"
    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"blog_posts", "blog_images", "blog_comments"} <= tables
    assert conn.execute("SELECT COUNT(*) FROM blog_posts").fetchone()[0] == 1
    conn.close()

    assert run.main(args) == 0
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM blog_posts").fetchone()[0] == 1
    conn.close()
    assert (tmp_path / "wiki" / "Источники" / "Блоги" / "Блог a-detal 304.md").exists()


def test_rebuild_recreates_the_database_from_scratch(tmp_path):
    # I7: правку парсеров подхватывает ТОЛЬКО пересоздание базы —
    # у команды должен быть явный способ это сделать.
    args = _args(tmp_path, "ingest", "--rebuild")
    assert run.main(args) == 0
    db_path = tmp_path / "forum.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO posts(mid, tid, page_no, text) VALUES (1, 1, 1, 'мусор')")
    conn.commit(); conn.close()
    assert run.main(args) == 0
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM posts WHERE mid = 1").fetchone()[0] == 0


def test_check_reports_findings_and_exit_code(tmp_path):
    # Проверка целостности должна ГОВОРИТЬ ненулевым кодом возврата, иначе
    # её нельзя поставить в конец прогона и уйти.
    wiki = tmp_path / "wiki" / "Источники"
    wiki.mkdir(parents=True)
    (wiki / "Тема 1.md").write_text("[[Тема 404]]\n", encoding="utf-8")
    assert run.main(["check", "--wiki", str(tmp_path / "wiki")]) == 1
    (wiki / "Тема 1.md").write_text("чисто\n", encoding="utf-8")
    assert run.main(["check", "--wiki", str(tmp_path / "wiki")]) == 0


def test_check_walks_the_whole_wiki_not_only_the_mirror(tmp_path):
    # Проверять надо всё дерево вики: статьи следующей фазы ссылаются на
    # источники, и обе стороны должны попадать в один проход.
    wiki = tmp_path / "wiki"
    (wiki / "Источники").mkdir(parents=True)
    (wiki / "Статьи" / "Тормоза").mkdir(parents=True)
    (wiki / "Источники" / "Тема 1.md").write_text("##### Пост 100\n\nа\n", encoding="utf-8")
    (wiki / "Статьи" / "Тормоза" / "Суппорт.md").write_text(
        "[[Тема 1#Пост 100]] и [[Тема 1#Пост 999]]\n", encoding="utf-8")
    assert run.main(["check", "--wiki", str(wiki)]) == 1


def test_mirror_and_coverage_refuse_a_missing_database(tmp_path, capsys):
    # Подкоманда генерации не должна создавать базу на лету: пустая база —
    # это не «нечего генерировать», это пропущенный шаг загрузки или
    # опечатка в --db. Раньше такой прогон писал 0 заметок и сносил зеркало.
    missing = tmp_path / "нет-такой.sqlite"
    for cmd in ("mirror", "coverage"):
        rc = run.main([cmd, "--db", str(missing), "--wiki", str(tmp_path / "wiki"),
                       "--csv", str(tmp_path / "c.csv")])
        assert rc == 2
        assert not missing.exists(), "база не должна создаваться подкомандой " + cmd
    assert "не найдена" in capsys.readouterr().out


def test_mirror_on_empty_database_does_not_wipe_the_mirror(tmp_path, capsys):
    # Сквозная проверка предохранителя через точку входа: код возврата
    # ненулевой, заметки на месте.
    wiki = tmp_path / "wiki" / "Источники"
    wiki.mkdir(parents=True)
    (wiki / "Тема 10045.md").write_text("настоящая заметка\n", encoding="utf-8")
    empty = tmp_path / "empty.sqlite"
    from pipeline import db as _db
    _db.init_schema(_db.connect(empty))

    rc = run.main(["mirror", "--db", str(empty), "--wiki", str(tmp_path / "wiki")])
    assert rc == 2
    assert (wiki / "Тема 10045.md").exists()
    assert "не тронуто" in capsys.readouterr().out


def test_ingest_still_creates_the_database(tmp_path):
    # Загрузчику базу создавать — прямая обязанность.
    assert run.main(_args(tmp_path, "ingest")) == 0
    assert (tmp_path / "forum.sqlite").exists()


def test_assets_without_action_reports_error(tmp_path, capsys):
    rc = run.main(["assets", "--db", str(tmp_path / "forum.sqlite")])
    assert rc == 2
    assert "assets index" in capsys.readouterr().out


def test_assets_index_runs_and_syncs_db_once(tmp_path, monkeypatch):
    # Сквозная проверка через точку входа: подкоманда `assets index` должна
    # дойти до fetch_assets.index_pending и синхронизировать манифест с базой
    # РОВНО один раз по завершении — не в цикле по URL (см. докстринг run.py).
    from pipeline import assets_state, db as _db, fetch_assets

    db_path = tmp_path / "forum.sqlite"
    conn = _db.connect(db_path); _db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://dead/x.jpg','pending')")
    conn.commit(); conn.close()

    # index_pending ищет через cdx_find_snapshot (matchType=prefix), не через
    # cdx_snapshots (matchType=exact) — мок не по той функции молча бил бы
    # в живой архив на каждом прогоне набора тестов (найдено ревью лида).
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_find_snapshot", lambda url, **kw: None)

    sync_calls = []
    real_sync = assets_state.sync_to_db

    def counting_sync(conn, manifest, assets_root):
        sync_calls.append(1)
        return real_sync(conn, manifest, assets_root)

    monkeypatch.setattr(assets_state, "sync_to_db", counting_sync)

    manifest = tmp_path / "assets-manifest.jsonl"
    rc = run.main(["assets", "index", "--db", str(db_path), "--assets-manifest", str(manifest),
                   "--assets-root", str(tmp_path / "assets")])
    assert rc == 0
    assert len(sync_calls) == 1

    row = sqlite3.connect(db_path).execute(
        "SELECT status FROM attachments WHERE url='http://dead/x.jpg'").fetchone()
    assert row == ("no_snapshot",)  # sync_to_db реально применил манифест к базе


def test_site_without_action_or_section_reports_error(tmp_path, capsys):
    assert run.main(["site"]) == 2
    assert "site build" in capsys.readouterr().out
    assert run.main(["site", "build"]) == 2  # раздел не указан


def test_site_build_writes_a_plan_file(tmp_path, monkeypatch):
    from pipeline import fetch_site

    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots",
                         lambda url, **kw: [("20100101000000", "http://subaru-faq.ru/faq/index.php?ELEMENT_ID=1")])
    rc = run.main(["site", "build", "faq", "--site-root", str(tmp_path / "site")])
    assert rc == 0
    assert (tmp_path / "site" / "plan-faq.json").exists()


def test_site_fetch_without_a_saved_plan_reports_error(tmp_path, capsys):
    rc = run.main(["site", "fetch", "faq", "--site-root", str(tmp_path / "site")])
    assert rc == 2
    assert "site build" in capsys.readouterr().out


def test_site_build_then_fetch_end_to_end(tmp_path, monkeypatch):
    # Сквозная проверка через точку входа: build сохраняет план на диск,
    # fetch читает ИМЕННО его — CDX для построения плана вызывается ровно
    # один раз за весь прогон (перезапуск fetch не должен спрашивать снова).
    from pipeline import fetch_site

    cdx_calls = []

    def fake_cdx(url, **kw):
        cdx_calls.append((url, kw))
        return [("20100101000000", "http://subaru-faq.ru/blogs/index.php?page=post&blog=x&post_id=1")]

    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", fake_cdx)
    site_root = tmp_path / "site"
    rc = run.main(["site", "build", "blogs", "--site-root", str(site_root)])
    assert rc == 0
    assert len(cdx_calls) == 1  # build — один запрос CDX на раздел

    monkeypatch.setattr(fetch_site.fetcher, "fetch_snapshot",
                         lambda ts, url, **kw: b'<div class="blog-post">post ' + b"x" * 2000 + b"</div>")
    manifest = tmp_path / "manifest-site.jsonl"
    rc = run.main(["site", "fetch", "blogs", "--site-root", str(site_root), "--site-manifest", str(manifest)])
    assert rc == 0
    assert len(cdx_calls) == 1  # fetch читает сохранённый план, CDX по новой не спрашивает
    assert list((site_root / "blogs").glob("*.html"))


def test_site_fetch_resumes_after_an_interruption_without_rebuilding_the_plan(tmp_path, monkeypatch):
    # Требование лида: суточный прогон может оборваться на середине —
    # повторный запуск обязан читать план С ДИСКА и докачивать только то,
    # что осталось, а не строить план заново (второй CDX-запрос за тем же
    # списком) и не перекачивать уже скачанное.
    from pipeline import fetch_site

    build_cdx_calls = []

    def fake_cdx(url, **kw):
        build_cdx_calls.append((url, kw))
        return [("20100101000000", "http://subaru-faq.ru/blogs/index.php?page=post&blog=x&post_id=%d" % i)
                for i in range(4)]

    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", fake_cdx)
    site_root = tmp_path / "site"
    manifest = tmp_path / "manifest-site.jsonl"
    assert run.main(["site", "build", "blogs", "--site-root", str(site_root)]) == 0
    assert len(build_cdx_calls) == 1  # build — ровно один запрос CDX на весь раздел

    fetch_calls = []
    monkeypatch.setattr(fetch_site.fetcher, "fetch_snapshot",
                         lambda ts, url, **kw: fetch_calls.append(url) or
                         (b'<div class="blog-post">post ' + b"x" * 2000 + b"</div>"))

    # "прогон оборвался" — качаем только половину одной командой (--limit)
    rc = run.main(["site", "fetch", "blogs", "--site-root", str(site_root),
                   "--site-manifest", str(manifest), "--limit", "2"])
    assert rc == 0
    assert len(fetch_calls) == 2
    assert len(build_cdx_calls) == 1  # ни один шаг fetch не звал CDX за планом заново

    # "перезапуск после обрыва" — та же команда, без --limit, план не пересчитывается
    fetch_calls.clear()
    rc = run.main(["site", "fetch", "blogs", "--site-root", str(site_root),
                   "--site-manifest", str(manifest)])
    assert rc == 0
    assert len(build_cdx_calls) == 1  # по-прежнему один — план читается с диска, не строится заново
    assert len(fetch_calls) == 2  # докачаны только оставшиеся 2 из 4, не все 4 заново

    from pipeline import assets_state
    state = assets_state.load(manifest)
    assert len(state) == 4
    assert all(v["status"] == "ok" for v in state.values())
    assert len(list((site_root / "blogs").glob("*.html"))) == 4


def test_assets_download_uses_assets_root_and_manifest(tmp_path, monkeypatch):
    from pipeline import assets_state, db as _db, fetch_assets

    db_path = tmp_path / "forum.sqlite"
    conn = _db.connect(db_path); _db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/x.jpg','pending')")
    conn.commit(); conn.close()

    manifest = tmp_path / "assets-manifest.jsonl"
    assets_state.record(manifest, "http://h/x.jpg", None, "pending", note="20150101")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    # Валидная сигнатура И правдоподобный размер (600x400): после просева
    # заглушек (Ruling 45) картинка 0x0 признаётся пустышкой, и правильно —
    # «сигнатура валидна» больше не значит «в файле картинка».
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
           + (600).to_bytes(4, "big") + (400).to_bytes(4, "big") + b"\x00" * 30)
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: png)

    assets_root = tmp_path / "assets"
    rc = run.main(["assets", "download", "--db", str(db_path), "--assets-manifest", str(manifest),
                   "--assets-root", str(assets_root)])
    assert rc == 0
    # Файл лёг именно в переданный --assets-root, а расширение — ПО БАЙТАМ
    # (Ruling 38): тело здесь PNG, хотя адрес обещает .jpg, и на диске
    # оказывается .png. Раньше расширение брали из адреса, и вложения
    # `show_file.php?fid=N` получали имя `<hash>.php` — механически целое,
    # но Obsidian такую вставку картинкой не показывает.
    assert list(assets_root.rglob("*.png"))
    assert not list(assets_root.rglob("*.jpg"))

    row = sqlite3.connect(db_path).execute(
        "SELECT status FROM attachments WHERE url='http://h/x.jpg'").fetchone()
    assert row == ("ok",)


def test_facts_command_reads_writes_and_reports_stats(tmp_path, capsys):
    from pipeline import db as _db

    wiki = tmp_path / "wiki"
    (wiki / "Источники").mkdir(parents=True)
    (wiki / "Источники" / "Тема 1.md").write_text(
        "##### Пост 100\n\n*Razum · 11.10.2014 12:00:00 · #1*\n\nТрубки нужны 3/16 дюйма.\n",
        encoding="utf-8")

    db_path = tmp_path / "forum.sqlite"
    conn = _db.connect(db_path)
    _db.init_schema(conn)
    conn.execute("INSERT INTO posts(mid, tid, author, posted_at, text, markdown) "
                 "VALUES (100, 1, 'Razum', '2014-10-11 12:00:00', '', '')")
    conn.commit()
    conn.close()

    articles = tmp_path / "articles"
    (articles / "факты").mkdir(parents=True)
    raw = [
        {"источник": "Тема 1#Пост 100", "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр"},
        {"источник": "Тема 1#Пост 100", "цитата": "выдумка", "суть": "враньё"},
    ]
    (articles / "факты" / "тормоза.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    rc = run.main(["facts", "--key", "тормоза", "--wiki", str(wiki), "--mirror-dir", "Источники",
                   "--db", str(db_path), "--articles-dir", str(articles)])
    assert rc == 0

    out = json.loads((articles / "проверено" / "тормоза.json").read_text(encoding="utf-8"))
    assert out["статистика"] == {"всего": 2, "прошло": 1, "отброшено": 1}
    assert out["проверено"][0]["автор"] == "Razum"
    assert out["проверено"][0]["дата"] == "11.10.2014"
    # Отброшенные факты остаются В ТОМ ЖЕ файле — доля брака входит в
    # замеры фазы, теряться она не должна (бриф задачи 4, шаг 5).
    assert len(out["отброшено"]) == 1
    assert out["отброшено"][0]["факт"]["цитата"] == "выдумка"
    assert "факты:" in capsys.readouterr().out


def test_facts_command_requires_key(tmp_path, capsys):
    rc = run.main(["facts", "--wiki", str(tmp_path / "wiki"), "--db", str(tmp_path / "x.sqlite")])
    assert rc == 2
    assert "--key" in capsys.readouterr().out


def test_facts_command_requires_existing_facts_file(tmp_path, capsys):
    rc = run.main(["facts", "--key", "нет-такого", "--articles-dir", str(tmp_path / "articles"),
                   "--db", str(tmp_path / "x.sqlite"), "--wiki", str(tmp_path / "wiki")])
    assert rc == 2
    assert "не найден" in capsys.readouterr().out


def test_facts_command_requires_existing_db(tmp_path, capsys):
    # Отсутствующая база — не повод молча проверять факты без атрибуции
    # (см. коммент run.main про coverage/mirror: то же правило).
    (tmp_path / "articles" / "факты").mkdir(parents=True)
    (tmp_path / "articles" / "факты" / "key.json").write_text("[]", encoding="utf-8")
    rc = run.main(["facts", "--key", "key", "--articles-dir", str(tmp_path / "articles"),
                   "--db", str(tmp_path / "missing.sqlite"), "--wiki", str(tmp_path / "wiki")])
    assert rc == 2
    assert "не найдена" in capsys.readouterr().out


# --- команда article (Ф3, задача 5, проход 2) -------------------------------


def test_article_command_builds_note_from_draft_and_verified_facts(tmp_path, capsys):
    (tmp_path / "articles" / "черновики").mkdir(parents=True)
    (tmp_path / "articles" / "проверено").mkdir(parents=True)
    (tmp_path / "articles" / "черновики" / "тормоза.md").write_text(
        "---\nзаголовок: Тормозные трубки\nузел: тормоза\nпуть: Тормоза\n"
        "собрано: 2026-08-21\n---\n\n"
        "Диаметр трубки — 4,75 мм[^f1].\n",
        encoding="utf-8")
    verified = {"проверено": [{"id": "f1", "источник": "Тема 42335#Пост 248484",
                                "цитата": "это 4,75 мм", "суть": "диаметр",
                                "автор": "Razum", "дата": "11.10.2014"}],
                "отброшено": [], "статистика": {"всего": 1, "прошло": 1, "отброшено": 0}}
    (tmp_path / "articles" / "проверено" / "тормоза.json").write_text(
        json.dumps(verified, ensure_ascii=False), encoding="utf-8")

    rc = run.main(["article", "--key", "тормоза", "--root", str(tmp_path)])
    assert rc == 0

    out_path = tmp_path / "wiki" / "Статьи" / "Тормоза" / "Тормозные трубки.md"
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert "[^f1]: «это 4,75 мм» — Razum, 11.10.2014, [[Тема 42335#Пост 248484]]" in text
    assert "статья собрана:" in capsys.readouterr().out


def test_article_command_requires_key(tmp_path, capsys):
    rc = run.main(["article", "--root", str(tmp_path)])
    assert rc == 2
    assert "--key" in capsys.readouterr().out


def test_article_command_reports_missing_draft_without_traceback(tmp_path, capsys):
    (tmp_path / "articles" / "проверено").mkdir(parents=True)
    rc = run.main(["article", "--key", "нет-такого", "--root", str(tmp_path)])
    assert rc == 2
    assert "ОШИБКА" in capsys.readouterr().out


def test_article_command_reports_missing_target_path_without_traceback(tmp_path, capsys):
    """Черновик без явного `путь` во frontmatter — `DraftError`, не трейсбек
    и не молчаливое угадывание папки узла (см. докстринг `articles.build`)."""
    (tmp_path / "articles" / "черновики").mkdir(parents=True)
    (tmp_path / "articles" / "проверено").mkdir(parents=True)
    (tmp_path / "articles" / "черновики" / "х.md").write_text(
        "---\nзаголовок: Х\nузел: тормоза\n---\n\nТекст[^f1].\n", encoding="utf-8")
    (tmp_path / "articles" / "проверено" / "х.json").write_text(
        json.dumps({"проверено": [{"id": "f1", "источник": "Тема 1#Пост 1",
                                    "цитата": "текст", "суть": "х"}]}, ensure_ascii=False),
        encoding="utf-8")
    rc = run.main(["article", "--key", "х", "--root", str(tmp_path)])
    assert rc == 2
    assert "ОШИБКА" in capsys.readouterr().out
