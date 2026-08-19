from pathlib import Path
from pipeline import assets_state, db


def test_record_and_load_roundtrip(tmp_path):
    m = tmp_path / "manifest-assets.jsonl"
    assets_state.record(m, "http://h/a.jpg", "assets/h/a.jpg", "ok")
    assets_state.record(m, "http://h/b.jpg", None, "no_snapshot", note="нет в CDX")
    st = assets_state.load(m)
    assert st["http://h/a.jpg"]["status"] == "ok"
    assert st["http://h/b.jpg"]["path"] is None


def test_last_record_wins(tmp_path):
    m = tmp_path / "manifest-assets.jsonl"
    assets_state.record(m, "http://h/a.jpg", None, "failed")
    assets_state.record(m, "http://h/a.jpg", "assets/h/a.jpg", "ok")
    assert assets_state.load(m)["http://h/a.jpg"]["status"] == "ok"


def test_sync_marks_missing_file_as_lost(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/a.jpg','pending')")
    conn.commit()
    m = tmp_path / "manifest-assets.jsonl"
    assets_state.record(m, "http://h/a.jpg", "assets/h/a.jpg", "ok")   # файла на диске нет
    stats = assets_state.sync_to_db(conn, m, tmp_path / "assets")
    row = conn.execute("SELECT local_path, status FROM attachments WHERE url='http://h/a.jpg'").fetchone()
    assert row == (None, "lost")
    assert stats["lost"] == 1


def test_sync_sets_local_path_when_file_exists(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/a.jpg','pending')")
    conn.commit()
    (tmp_path / "assets" / "h").mkdir(parents=True)
    (tmp_path / "assets" / "h" / "a.jpg").write_bytes(b"x" * 100)
    m = tmp_path / "manifest-assets.jsonl"
    assets_state.record(m, "http://h/a.jpg", "h/a.jpg", "ok")
    assets_state.sync_to_db(conn, m, tmp_path / "assets")
    assert conn.execute("SELECT local_path, status FROM attachments WHERE url='http://h/a.jpg'").fetchone() == ("h/a.jpg", "ok")


def test_sync_leaves_urls_absent_from_manifest_untouched(tmp_path):
    """Пустой (или частичный) манифест не должен трогать skip/pending — только то, что в нём есть."""
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'interface_image','http://h/skip.gif','skip')")
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (2,'external_image','http://h/pending.jpg','pending')")
    conn.commit()
    m = tmp_path / "manifest-assets.jsonl"  # манифест пуст — файла ещё нет
    stats = assets_state.sync_to_db(conn, m, tmp_path / "assets")
    rows = dict(conn.execute("SELECT url, status FROM attachments").fetchall())
    assert rows == {"http://h/skip.gif": "skip", "http://h/pending.jpg": "pending"}
    assert stats == {"ok": 0, "lost": 0, "no_snapshot": 0, "failed": 0, "unknown_url": 0}


def test_sync_updates_all_rows_sharing_one_url(tmp_path):
    """Одна картинка вставлена в несколько постов — несколько строк с одним url.
    Обновление по url обязано затронуть их все, а счётчик считать URL, а не строки."""
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/a.jpg','pending')")
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (2,'external_image','http://h/a.jpg','pending')")
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (3,'external_image','http://h/a.jpg','pending')")
    conn.commit()
    (tmp_path / "assets" / "h").mkdir(parents=True)
    (tmp_path / "assets" / "h" / "a.jpg").write_bytes(b"x" * 100)
    m = tmp_path / "manifest-assets.jsonl"
    assets_state.record(m, "http://h/a.jpg", "h/a.jpg", "ok")
    stats = assets_state.sync_to_db(conn, m, tmp_path / "assets")
    rows = conn.execute("SELECT local_path, status FROM attachments WHERE url='http://h/a.jpg'").fetchall()
    assert rows == [("h/a.jpg", "ok"), ("h/a.jpg", "ok"), ("h/a.jpg", "ok")]
    assert stats["ok"] == 1  # один URL, а не три строки


def test_sync_survives_interrupted_append_and_reruns_idempotently(tmp_path):
    """Манифест дописывается: обрыв прогона не теряет уже записанное,
    повторный запуск на том же манифесте видит прежнее состояние и не меняет результат."""
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/a.jpg','pending')")
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (2,'external_image','http://h/b.jpg','pending')")
    conn.commit()
    m = tmp_path / "manifest-assets.jsonl"
    (tmp_path / "assets" / "h").mkdir(parents=True)
    (tmp_path / "assets" / "h" / "a.jpg").write_bytes(b"x" * 10)

    # первый "прогон" записал a.jpg и оборвался до записи b.jpg
    assets_state.record(m, "http://h/a.jpg", "h/a.jpg", "ok")
    stats1 = assets_state.sync_to_db(conn, m, tmp_path / "assets")
    assert stats1 == {"ok": 1, "lost": 0, "no_snapshot": 0, "failed": 0, "unknown_url": 0}

    # перезапуск дописывает b.jpg в тот же файл, не переписывая его
    (tmp_path / "assets" / "h" / "b.jpg").write_bytes(b"y" * 10)
    assets_state.record(m, "http://h/b.jpg", "h/b.jpg", "ok")

    lines = m.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # обе записи на месте — ничего не потеряно и не переписано

    stats2 = assets_state.sync_to_db(conn, m, tmp_path / "assets")
    assert stats2 == {"ok": 2, "lost": 0, "no_snapshot": 0, "failed": 0, "unknown_url": 0}
    rows = dict(conn.execute("SELECT url, status FROM attachments").fetchall())
    assert rows == {"http://h/a.jpg": "ok", "http://h/b.jpg": "ok"}
