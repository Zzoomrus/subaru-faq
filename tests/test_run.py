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
            "--mirror-dir", "Источники"]


def test_all_runs_the_whole_pipeline(tmp_path):
    # Единственная точка входа: следующая фаза состоит из повторных прогонов,
    # heredoc в документе для этого не годится.
    assert run.main(_args(tmp_path, "all")) == 0
    assert (tmp_path / "forum.sqlite").exists()
    assert (tmp_path / "coverage.csv").exists()
    assert (tmp_path / "wiki" / "Источники" / "Тема 10045.md").exists()


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
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot",
                         lambda ts, url, **kw: b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)

    assets_root = tmp_path / "assets"
    rc = run.main(["assets", "download", "--db", str(db_path), "--assets-manifest", str(manifest),
                   "--assets-root", str(assets_root)])
    assert rc == 0
    assert list(assets_root.rglob("*.jpg"))  # файл лёг именно в переданный --assets-root (имя — по URL)

    row = sqlite3.connect(db_path).execute(
        "SELECT status FROM attachments WHERE url='http://h/x.jpg'").fetchone()
    assert row == ("ok",)
