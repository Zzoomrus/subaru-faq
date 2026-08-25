import json
from pathlib import Path

from pipeline import archive_assets, assets_state, db, fetch_faqblog_assets

PNG_SIG = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
           + (600).to_bytes(4, "big") + (400).to_bytes(4, "big") + b"\x00" * 30)


def _db(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    db.init_schema(conn)
    return conn


def _empty_archive(tmp_path):
    """Архив Ф0/Ф1 без единого файла — как в постановке: у этих 262 адресов
    в архиве нет ничего (проверено на боевой базе)."""
    manifest = tmp_path / "manifest-assets.jsonl"
    manifest.write_text("", encoding="utf-8")
    return manifest, tmp_path / "archive"


def test_pool_excludes_urls_already_covered_by_the_archive(tmp_path):
    """URL, который archive_assets.find находит в архиве Ф0/Ф1, не должен
    стать целью Wayback-добора вовсе — незачем спрашивать архив про то, что
    уже есть на диске без всякой сети (иначе тратим вежливость впустую)."""
    root = tmp_path / "archive"
    (root / "upload/blog/aaa").mkdir(parents=True)
    (root / "upload/blog/aaa/live.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 40)
    manifest = tmp_path / "manifest-assets.jsonl"
    manifest.write_text(json.dumps({"path": "upload/blog/aaa/live.jpg"}) + "\n", encoding="utf-8")

    conn = _db(tmp_path)
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md) VALUES ('bitrix', 1, 'в', 'о')")
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES "
                 "('bitrix', 1, 'http://subaru-faq.ru/upload/blog/aaa/live.jpg')")   # в архиве
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES "
                 "('bitrix', 1, 'http://s017.radikal.ru/i416/x.jpg')")               # не в архиве
    conn.commit()

    index = archive_assets.load_index(manifest)
    urls = fetch_faqblog_assets._target_urls(conn, index, root)
    assert urls == ["http://s017.radikal.ru/i416/x.jpg"]


def test_pool_is_union_of_faq_and_blog_tables(tmp_path):
    manifest, root = _empty_archive(tmp_path)
    conn = _db(tmp_path)
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md) VALUES ('bitrix', 1, 'в', 'о')")
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES ('bitrix', 1, 'http://h/faq.jpg')")
    conn.execute("INSERT INTO blog_images(blog, post_id, url) VALUES ('remont', 1, 'http://h/blog.jpg')")
    conn.commit()
    index = archive_assets.load_index(manifest)
    urls = fetch_faqblog_assets._target_urls(conn, index, root)
    assert urls == ["http://h/blog.jpg", "http://h/faq.jpg"]


def test_index_and_download_roundtrip(tmp_path, monkeypatch):
    manifest, archive_root = _empty_archive(tmp_path)
    conn = _db(tmp_path)
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md) VALUES ('bitrix', 1, 'в', 'о')")
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES ('bitrix', 1, 'http://h/x.jpg')")
    conn.commit()

    m = tmp_path / "manifest-faqblog.jsonl"
    monkeypatch.setattr(fetch_faqblog_assets.fetcher, "cdx_find_snapshot",
                        lambda url, **kw: ("20150101", url))
    stats = fetch_faqblog_assets.index_pending(conn, m, archive_manifest=manifest,
                                                archive_root=archive_root)
    assert stats == {"pending": 1, "no_snapshot": 0}

    monkeypatch.setattr(fetch_faqblog_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    monkeypatch.setattr(fetch_faqblog_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: PNG_SIG)
    assets_root = tmp_path / "files"
    stats = fetch_faqblog_assets.download(conn, m, assets_root, archive_manifest=manifest,
                                           archive_root=archive_root)
    assert stats == {"ok": 1, "empty": 0, "failed": 0}
    rec = assets_state.load(m)["http://h/x.jpg"]
    assert rec["status"] == "ok"
    assert (assets_root / rec["path"]).exists()


def test_download_rejects_a_placeholder_pixel(tmp_path, monkeypatch):
    """Проверка содержимого, не кода ответа (урок фазы Ф2/Ruling 45): 1x1
    GIF — валидная сигнатура, но заглушка хостинга, а не картинка поста."""
    manifest, archive_root = _empty_archive(tmp_path)
    conn = _db(tmp_path)
    conn.execute("INSERT INTO blog_images(blog, post_id, url) VALUES ('remont', 1, 'http://h/x.gif')")
    conn.commit()
    m = tmp_path / "manifest-faqblog.jsonl"
    assets_state.record(m, "http://h/x.gif", None, "pending", note="20150101")
    tiny_gif = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    monkeypatch.setattr(fetch_faqblog_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    monkeypatch.setattr(fetch_faqblog_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: tiny_gif)
    stats = fetch_faqblog_assets.download(conn, m, tmp_path / "files", archive_manifest=manifest,
                                           archive_root=archive_root)
    assert stats == {"ok": 0, "empty": 1, "failed": 0}


def test_sync_to_db_only_touches_rows_still_null(tmp_path):
    """`archive_assets.sync_local_paths` уже мог заполнить `local_path` —
    этот sync не должен его трогать (пулы не пересекаются по построению, но
    предохранитель `WHERE local_path IS NULL` в SQL защищает от регрессии)."""
    conn = _db(tmp_path)
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md) VALUES ('bitrix', 1, 'в', 'о')")
    conn.execute("INSERT INTO faq_images(engine, nr, url, local_path) VALUES "
                 "('bitrix', 1, 'http://archive/already.jpg', 'upload/already.jpg')")
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES ('bitrix', 1, 'http://h/new.jpg')")
    conn.execute("INSERT INTO blog_images(blog, post_id, url) VALUES ('remont', 1, 'http://h/lost.jpg')")
    conn.commit()

    m = tmp_path / "manifest-faqblog.jsonl"
    assets_root = tmp_path / "files"
    (assets_root / "h").mkdir(parents=True)
    (assets_root / "h/new.jpg").write_bytes(b"data")
    assets_state.record(m, "http://h/new.jpg", "h/new.jpg", "ok")
    assets_state.record(m, "http://h/lost.jpg", None, "no_snapshot")
    # Заведомо ложная запись на уже-архивный URL — не должна ничего сломать,
    # потому что строка с этим url в базе уже НЕ NULL (SQL-фильтр).
    assets_state.record(m, "http://archive/already.jpg", "h/should-not-apply.jpg", "ok")

    stats = fetch_faqblog_assets.sync_to_db(conn, m, assets_root)
    assert stats == {"faq_ok": 1, "faq_lost": 0, "blog_ok": 0, "blog_lost": 1}
    rows = dict(conn.execute("SELECT url, local_path FROM faq_images").fetchall())
    assert rows["http://h/new.jpg"] == "h/new.jpg"
    assert rows["http://archive/already.jpg"] == "upload/already.jpg"    # не тронуто
    lost = dict(conn.execute("SELECT url, local_path FROM blog_images").fetchall())
    assert lost["http://h/lost.jpg"] is None


def test_sync_to_db_nulls_out_ok_status_with_a_missing_file(tmp_path):
    """Манифест обещает файл, а на диске его нет — та же логика "lost", что
    у `assets_state.sync_to_db`/`archive_assets.sync_local_paths`."""
    conn = _db(tmp_path)
    conn.execute("INSERT INTO blog_images(blog, post_id, url) VALUES ('remont', 1, 'http://h/gone.jpg')")
    conn.commit()
    m = tmp_path / "manifest-faqblog.jsonl"
    assets_state.record(m, "http://h/gone.jpg", "h/gone.jpg", "ok")
    stats = fetch_faqblog_assets.sync_to_db(conn, m, tmp_path / "files")   # файла нет на диске
    assert stats == {"faq_ok": 0, "faq_lost": 0, "blog_ok": 0, "blog_lost": 1}


def test_cli_faqblog_command_wires_up(tmp_path):
    """Дымовой тест CLI: `faqblog index/download/sieve` не падают на пустой
    базе и печатают статистику — так же, как `assets` у формы."""
    from pipeline import run
    db_path = tmp_path / "f.sqlite"
    m = tmp_path / "m.jsonl"
    root = tmp_path / "files"
    rc = run.main(["faqblog", "index", "--db", str(db_path),
                   "--faqblog-manifest", str(m), "--assets-root", str(root)])
    assert rc == 0
    rc = run.main(["faqblog", "download", "--db", str(db_path),
                   "--faqblog-manifest", str(m), "--assets-root", str(root)])
    assert rc == 0
    rc = run.main(["faqblog", "sieve", "--db", str(db_path),
                   "--faqblog-manifest", str(m), "--assets-root", str(root)])
    assert rc == 0


def test_cli_faqblog_reports_a_bad_retry_flag_with_exit_code(tmp_path, capsys):
    from pipeline import run
    rc = run.main(["faqblog", "download", "--db", str(tmp_path / "f.sqlite"),
                   "--faqblog-manifest", str(tmp_path / "m.jsonl"),
                   "--assets-root", str(tmp_path / "a"), "--retry", "ok"])
    assert rc == 2
    assert "нельзя перезапросить статус" in capsys.readouterr().out
