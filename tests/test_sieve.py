"""Просев заглушек хостингов (Ruling 45, находка Б1 ре-ревью).

75 из 1859 вставок боевой вики оказались не фотографиями: 55 файлов по 43
байта (1x1 GIF — трекинг-пиксель, который `i.piccy.info` отдаёт вместо
удалённого файла), 18 байт-идентичных 200x236 (баннер `images.vfl.ru`
«изображение было удалено») и 2 файла 1x1 JPEG. Все механически целы:
сигнатура валидна, файл существует, проверка целостности даёт четыре нуля, и
все посчитаны внутри главной цифры фазы «1484 картинки возвращены».

Третий вариант урока фазы: «вставка цела» != «вставка на месте» != «в файле
вообще картинка».

Ключевое в устройстве просева — ДВА РАЗНЫХ РЕЖИМА, и тесты проверяют именно
разделение: однозначный признак (сторона <= 2 px) метится машинально,
неоднозначный (байт-идентичность у трёх и более адресов) только
перечисляется человеку.
"""
import hashlib
import struct
from pathlib import Path

from pipeline import assets_state, attachments, db, fetch_assets

GIF_1X1 = b"GIF89a" + struct.pack("<HH", 1, 1) + b"\x80\x00\x00" + b"\x00" * 20
GIF_600 = b"GIF89a" + struct.pack("<HH", 600, 400) + b"\x80\x00\x00" + b"\x00" * 20
PNG_1X2 = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4 + b"IHDR" + struct.pack(">II", 1, 2) + b"\x00" * 20
PNG_800 = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4 + b"IHDR" + struct.pack(">II", 800, 600) + b"\x00" * 20


def test_image_size_reads_the_common_formats():
    assert attachments.image_size(GIF_600) == (600, 400)
    assert attachments.image_size(PNG_800) == (800, 600)
    assert attachments.image_size(b"BM" + b"\x00" * 16 + struct.pack("<ii", 320, -240)) == (320, 240)
    # Не картинка и обрезанный заголовок — «не знаю», а не падение.
    assert attachments.image_size(b"%PDF-1.4") is None
    assert attachments.image_size(b"GIF89a") is None
    assert attachments.image_size(b"") is None


def test_placeholder_is_only_the_unambiguous_case():
    assert attachments.looks_like_placeholder(GIF_1X1)
    assert attachments.looks_like_placeholder(PNG_1X2)          # сторона 1 при высоте 2
    assert not attachments.looks_like_placeholder(GIF_600)
    assert not attachments.looks_like_placeholder(PNG_800)
    # Документ картинкой не считается вовсе, значит и заглушкой быть не может.
    assert not attachments.looks_like_placeholder(b"%PDF-1.4" + b"\x00" * 40)
    # Размер не прочитался -> НЕ заглушка: пометить содержимое утраченным по
    # незнанию хуже, чем пропустить заглушку.
    assert not attachments.looks_like_placeholder(b"\xff\xd8\xff" + b"\x00" * 8)


def test_download_no_longer_accepts_a_placeholder_body(tmp_path, monkeypatch):
    # Иначе добор Ф3 принёс бы тот же класс снова: 43-байтный 1x1 GIF — это
    # валидный GIF, и старый признак содержимого его принимал.
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) "
                 "VALUES (1,'external_image','http://h/pixel.gif','pending')")
    conn.commit()
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/pixel.gif", None, "pending", note="20150101")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: GIF_1X1)
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats == {"ok": 0, "empty": 1, "failed": 0}
    assert assets_state.load(m)["http://h/pixel.gif"]["status"] == "empty"
    assert not list((tmp_path / "assets").rglob("*"))       # файл не сохранён


def _seeded(tmp_path, files):
    """files: url -> байты. Кладёт файлы и манифест как после добора."""
    conn = db.connect(tmp_path / "s.sqlite"); db.init_schema(conn)
    manifest = tmp_path / "m.jsonl"
    root = tmp_path / "files"
    for i, (url, data) in enumerate(files.items(), 1):
        rel = fetch_assets.local_name(url, data)
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                     "VALUES (?, 'external_image', ?, ?, 'ok')", (i, url, rel))
        assets_state.record(manifest, url, rel, "ok")
    conn.commit()
    return conn, manifest, root


def test_sieve_separates_the_two_kinds_of_evidence(tmp_path):
    # Однозначное метим, неоднозначное перечисляем. Три адреса с ОДНИМИ
    # байтами нормального размера — это может быть и заглушка хостинга, и одна
    # настоящая фотография, вставленная трижды. Машина такое не решает.
    same = GIF_600 + "одни и те же байты".encode()
    conn, manifest, root = _seeded(tmp_path, {
        "http://h/a/pixel.gif": GIF_1X1,
        "http://h/b/pixel.gif": GIF_1X1 + b"",
        "http://h/1.gif": same,
        "http://h/2.gif": same,
        "http://h/3.gif": same,
        "http://h/real.png": PNG_800 + "настоящая".encode(),
    })
    report = fetch_assets.sieve_report(conn, manifest, root)
    assert sorted(i["url"] for i in report["placeholders"]) == [
        "http://h/a/pixel.gif", "http://h/b/pixel.gif"]
    assert len(report["identical_groups"]) == 1
    group = report["identical_groups"][0]
    assert group["urls"] == 3 and group["size"] == (600, 400)
    # Группа только описана — ни один её адрес не помечен и статус не тронут.
    assert all("1.gif" not in i["url"] for i in report["placeholders"])
    assert assets_state.load(manifest)["http://h/1.gif"]["status"] == "ok"


def test_sieve_report_touches_nothing_until_asked(tmp_path):
    conn, manifest, root = _seeded(tmp_path, {"http://h/pixel.gif": GIF_1X1})
    before = manifest.read_text(encoding="utf-8")
    fetch_assets.sieve_report(conn, manifest, root)
    assert manifest.read_text(encoding="utf-8") == before
    assert (root / fetch_assets.local_name("http://h/pixel.gif", GIF_1X1)).exists()


def test_mark_empty_makes_the_address_terminal_and_lost(tmp_path):
    conn, manifest, root = _seeded(tmp_path, {"http://h/pixel.gif": GIF_1X1,
                                               "http://h/real.png": PNG_800 + "настоящая".encode()})
    report = fetch_assets.sieve_report(conn, manifest, root)
    assert fetch_assets.mark_empty(manifest, [i["url"] for i in report["placeholders"]]) == 1

    state = assets_state.load(manifest)
    assert state["http://h/pixel.gif"]["status"] == "empty"
    assert state["http://h/pixel.gif"]["path"] is None
    assert state["http://h/real.png"]["status"] == "ok"

    # Синхронизация переносит это в базу: у заглушки больше нет local_path,
    # значит генератор поставит честную пометку об утрате.
    stats = assets_state.sync_to_db(conn, manifest, root)
    assert stats["empty"] == 1 and stats["ok"] == 1
    rows = dict(conn.execute("SELECT url, local_path FROM attachments").fetchall())
    assert rows["http://h/pixel.gif"] is None
    assert rows["http://h/real.png"] is not None

    # И повторный прогон её не перекачает: `empty` терминален без явного флага.
    assert fetch_assets._targets(conn, manifest, "download", None) == []


DECIDED_SHA256 = "ec872606e266d9774a98276ab0d9e19a1155304c8180a879fedb7189ffde59f1"


def test_side_rule_does_not_depend_on_size_or_hash_of_a_particular_tracker():
    """Условие лида: правило по стороне — САМОСТОЯТЕЛЬНОЕ.

    Найденный трекер был 43-байтным GIF, но 43 байта и его хэш — приметы
    ОДНОГО хостинга, а сторона — признак класса. Добор Ф3 принесёт другой
    трекер: другой формат, другой размер файла, другой хэш.
    """
    other_tracker = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
                     + (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + b"\x00" * 900)
    assert len(other_tracker) != 43
    assert attachments.looks_like_placeholder(other_tracker)
    assert attachments.decided_placeholder(other_tracker) is None    # хэш ни при чём
    assert not fetch_assets._is_real_image(other_tracker)


def test_byte_identity_is_diagnostics_and_the_verdict_is_a_human_decision(tmp_path):
    """Условие лида: байт-идентичность НЕ становится автоматическим правилом.

    Иначе первая же настоящая фотография, выложенная на трёх шардах
    фотохостинга, тихо исчезла бы из вики. В коде помечены конкретные
    решённые файлы (по sha256 — тут он уместен, это приговор одному файлу),
    а не «три и более адресов → заглушка».
    """
    photo = GIF_600 + "настоящая фотография с трёх шардов".encode()
    conn, manifest, root = _seeded(tmp_path, {
        "http://s1.host/p.gif": photo,
        "http://s2.host/p.gif": photo,
        "http://s3.host/p.gif": photo,
    })
    report = fetch_assets.sieve_report(conn, manifest, root)
    # Три адреса, одни байты — но приговора нет, значит и пометки нет.
    assert report["placeholders"] == []
    assert len(report["identical_groups"]) == 1 and report["identical_groups"][0]["urls"] == 3
    assert not attachments.is_placeholder(photo)
    # И проверка содержимого при скачивании такую фотографию принимает.
    assert fetch_assets._is_real_image(photo)


def test_a_decided_verdict_marks_the_file_and_names_the_ground(tmp_path):
    # Приговор из `DECIDED_PLACEHOLDER_SHA256` работает и в просеве, и в
    # проверке содержимого при скачивании — с указанием основания, а не
    # безымянно.
    assert DECIDED_SHA256 in attachments.DECIDED_PLACEHOLDER_SHA256
    assert attachments.decided_placeholder("не заглушка".encode()) is None
    # Проверяем механику приговора на своём хэше, не завися от корпуса.
    data = GIF_600 + "решённая глазами заглушка".encode()
    digest = hashlib.sha256(data).hexdigest()
    attachments.DECIDED_PLACEHOLDER_SHA256[digest] = "проба"
    try:
        assert attachments.decided_placeholder(data) == "проба"
        assert attachments.is_placeholder(data)
        assert not attachments.looks_like_placeholder(data)   # правило класса тут молчит
        assert not fetch_assets._is_real_image(data)
    finally:
        del attachments.DECIDED_PLACEHOLDER_SHA256[digest]
