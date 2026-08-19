from pathlib import Path

from pipeline import db, fetch_assets, assets_state

# Минимальные валидные сигнатуры (не полноценные файлы, но с верным magic-байтом
# в начале — этого достаточно для сигнатурной проверки content_probe).
PNG_SIG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
PDF_SIG = b"%PDF-1.4\n" + b"\x00" * 40


def test_local_name_is_stable_and_safe():
    n1 = fetch_assets.local_name("http://s017.radikal.ru/i416/1308/40/2b6f4aa67490.jpg")
    n2 = fetch_assets.local_name("http://s017.radikal.ru/i416/1308/40/2b6f4aa67490.jpg")
    assert n1 == n2
    assert n1.endswith(".jpg") and ".." not in n1 and not n1.startswith("/")


def test_local_name_differs_for_same_basename_on_different_hosts():
    a = fetch_assets.local_name("http://host-a.ru/pics/1.jpg")
    b = fetch_assets.local_name("http://host-b.ru/pics/1.jpg")
    assert a != b


def test_index_marks_no_snapshot(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://dead/x.jpg','pending')")
    conn.commit()
    # index_pending ищет через cdx_find_snapshot (matchType=prefix по URL),
    # не через cdx_snapshots (matchType=exact) — см. правку после ревью лида
    # (task-3-report.md, "Живая правка после ревью лида").
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_find_snapshot", lambda url, **kw: None)
    m = tmp_path / "m.jsonl"
    stats = fetch_assets.index_pending(conn, m)
    assert stats["no_snapshot"] == 1
    assert assets_state.load(m)["http://dead/x.jpg"]["status"] == "no_snapshot"


def test_index_marks_pending_and_saves_the_timestamp(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/x.jpg','pending')")
    conn.commit()
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_find_snapshot",
                         lambda url, **kw: ("20200101000000", url))
    m = tmp_path / "m.jsonl"
    stats = fetch_assets.index_pending(conn, m)
    assert stats["pending"] == 1
    rec = assets_state.load(m)["http://h/x.jpg"]
    assert rec["status"] == "pending"
    assert rec["note"] == "20200101000000"


def test_download_skips_empty_snapshot(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/x.jpg','pending')")
    conn.commit()
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/x.jpg", None, "pending", note="20150101")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: b"<html></html>")
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats["empty"] == 1
    assert not list((tmp_path / "assets").rglob("*")) or stats["ok"] == 0


# --- дополнительные требования сверх брифа ---

def test_download_calls_cdx_exactly_once_per_url(tmp_path, monkeypatch):
    """Второй вызов CDX «просто чтобы отличить пустой снимок от отсутствия
    снимка» на тысячах адресов удвоил бы нагрузку на архив — этого не должно
    быть ни на удачном, ни на неудачном пути."""
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/x.jpg','pending')")
    conn.commit()
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/x.jpg", None, "pending", note="20150101")

    calls = []

    def counting_cdx(url, **kw):
        calls.append(url)
        return [("20150101", url)]

    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", counting_cdx)
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: b"<html></html>")
    fetch_assets.download(conn, m, tmp_path / "assets")
    assert len(calls) == 1


def test_download_uses_image_validity_not_antibot_marker(tmp_path, monkeypatch):
    """Антибот-маркер CleanTalk (ctSetCookie/ctMouseData) больше не признак
    пустышки: страница может нести его и при этом быть настоящей картинкой не
    касается — а вот сама распознаваемость изображения по сигнатуре обязана
    решать исход."""
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/x.jpg','pending')")
    conn.commit()
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/x.jpg", None, "pending", note="20150101")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    # Валидная сигнатура PNG, но с "антибот-маркером" внутри — раньше это
    # искалечило бы результат, если бы looks_empty решал по маркеру.
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot",
                         lambda ts, url, **kw: PNG_SIG + b"ctSetCookie ctMouseData")
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats["ok"] == 1


def test_download_rejects_invalid_image_bytes_for_external_image(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/x.jpg','pending')")
    conn.commit()
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/x.jpg", None, "pending", note="20150101")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: b"not an image" * 100)
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats["empty"] == 1
    assert stats["ok"] == 0


def test_download_accepts_document_signature_for_local_kind(tmp_path, monkeypatch):
    """`local` — собственные вложения форума без расширения в URL
    (`getfile?id=N`); реальный тип неизвестен заранее, поэтому признак
    содержимого — валидная сигнатура ЛЮБОГО известного формата (картинка ИЛИ
    документ), а не только картинки."""
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'local','http://forum/index.php?t=getfile&id=1','pending')")
    conn.commit()
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://forum/index.php?t=getfile&id=1", None, "pending", note="20150101")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: PDF_SIG)
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats["ok"] == 1


def test_download_rejects_unrecognized_bytes_for_local_kind(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'local','http://forum/index.php?t=getfile&id=1','pending')")
    conn.commit()
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://forum/index.php?t=getfile&id=1", None, "pending", note="20150101")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: b"<html>not archived</html>" * 10)
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats["empty"] == 1


def test_index_does_not_slow_the_pacer_down_on_a_low_hit_rate(tmp_path, monkeypatch):
    """`no_snapshot` — честный ответ CDX, а не сетевая неудача. Если бы пейсер
    считал его неудачей (как при скачивании тела), низкая выживаемость (в
    реальности ~15%) держала бы паузу на потолке весь прогон — замер на живом
    сервере показал десятки секунд на URL вместо ожидаемых секунд. Пейсер
    должен получать note(True) независимо от того, нашёлся снимок или нет."""
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    for i in range(5):
        conn.execute(
            "INSERT INTO attachments(mid, kind, url, status) VALUES (?, 'external_image', ?, 'pending')",
            (i, "http://dead/%d.jpg" % i))
    conn.commit()

    notes = []

    class FakePacer:
        def note(self, ok):
            notes.append(ok)

        def wait(self):
            pass

    monkeypatch.setattr(fetch_assets.fetcher, "TokenBucketPacer", FakePacer)
    # 4 из 5 URL без снимка — низкий hit rate, как в реальности (~15-25%).
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_find_snapshot",
                         lambda url, **kw: ("20150101", url) if "0" in url else None)
    m = tmp_path / "m.jsonl"
    fetch_assets.index_pending(conn, m)
    assert notes == [True] * 5


def test_download_marks_failed_when_every_snapshot_fetch_errors(tmp_path, monkeypatch):
    """Если снимки в CDX есть, но скачать тело ни одного не удалось (сеть),
    это `failed`, а не `empty` — «пустышка» это про содержимое, а не про сеть."""
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/x.jpg','pending')")
    conn.commit()
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/x.jpg", None, "pending", note="20150101")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url), ("20140101", url)])
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: None)
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats["failed"] == 1
    assert stats["empty"] == 0
