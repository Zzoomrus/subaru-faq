from pathlib import Path

from pipeline import db, fetch_assets, assets_state

# Минимальные валидные сигнатуры (не полноценные файлы, но с верным magic-байтом
# в начале — этого достаточно для сигнатурной проверки content_probe).
# Тело с валидной сигнатурой И ПРАВДОПОДОБНЫМ размером: с приходом просева
# заглушек (Ruling 45) «валидной сигнатуры» стало недостаточно — картинка
# 0x0 или 1x1 содержимым поста быть не может и признаётся пустышкой. Прежние
# фикстуры были `сигнатура + нули`, то есть 0x0, и после правки перестали
# проходить признак содержимого — правильно перестали: они изображали то,
# чего в корпусе не бывает.
PNG_SIG = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
           + (600).to_bytes(4, "big") + (400).to_bytes(4, "big") + b"\x00" * 30)
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


def test_download_does_not_call_cdx_at_all_when_saved_snapshot_works(tmp_path, monkeypatch):
    """Главное обещание переделки (задача 3, живая правка): если сохранённая
    индексацией метка снимка рабочая, скачивание идёт БЕЗ единого обращения
    к CDX — не «максимум один раз», а ноль раз на подавляющем большинстве
    адресов. Раньше это проверялось только чтением кода — ревьюер справедливо
    указал, что это не тест."""
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/x.jpg','pending')")
    conn.commit()
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/x.jpg", None, "pending", note="20150101")

    calls = []
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: calls.append(url))
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: PNG_SIG)
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats["ok"] == 1
    assert calls == []  # cdx_snapshots не вызван вовсе


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


def test_download_does_not_slow_the_pacer_down_on_empty_content(tmp_path, monkeypatch):
    """Пустышка по содержимому — не сетевая неудача (тело скачалось, значит
    сеть отработала), пейсер не должен её штрафовать — то же рассуждение,
    что уже применено к "снимков нет" в index_pending. Иначе череда пустышек
    подряд без всякой сетевой причины роняет темп скачивания до потолка
    паузы (найдено ревью лида)."""
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/x.jpg','pending')")
    conn.commit()
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/x.jpg", None, "pending", note="20150101")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: b"<html></html>")

    notes = []

    class FakePacer:
        def note(self, ok):
            notes.append(ok)

        def wait(self):
            pass

    monkeypatch.setattr(fetch_assets.fetcher, "TokenBucketPacer", FakePacer)
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats["empty"] == 1
    assert notes == [True]  # тело скачалось — сеть отработала, штрафа нет


def test_download_does_slow_the_pacer_down_on_a_real_network_failure(tmp_path, monkeypatch):
    """А вот настоящий сетевой сбой (тело не скачалось вовсе) пейсер
    штрафовать обязан — иначе он никогда не притормозит при реальной
    перегрузке/бане."""
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO attachments(mid, kind, url, status) VALUES (1,'external_image','http://h/x.jpg','pending')")
    conn.commit()
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/x.jpg", None, "pending", note="20150101")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: None)

    notes = []

    class FakePacer:
        def note(self, ok):
            notes.append(ok)

        def wait(self):
            pass

    monkeypatch.setattr(fetch_assets.fetcher, "TokenBucketPacer", FakePacer)
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats["failed"] == 1
    assert notes == [False]


def _seeded(tmp_path, *urls):
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    for i, url in enumerate(urls, 1):
        conn.execute("INSERT INTO attachments(mid, kind, url, status) "
                     "VALUES (?, 'external_image', ?, 'pending')", (i, url))
    conn.commit()
    return conn


def test_failed_is_retried_on_the_next_download_run(tmp_path, monkeypatch):
    # C1 итогового ревью Ф2 (Ruling 33): `failed` — утверждение о ПРОГОНЕ
    # («сеть не отдала ни одного тела»), а не об архиве. Пока он был
    # терминальным, 10 адресов боевого манифеста не пробовали больше никогда,
    # а повторный прогон печатал `{'ok': 0, ...}` и выглядел как успех.
    # Добор страниц сайта (`fetch_site.fetch_all`) всё это время
    # ПЕРЕзапрашивал failed штатно — два модуля решали одно противоположно.
    conn = _seeded(tmp_path, "http://h/x.jpg")
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/x.jpg", None, "failed")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: PNG_SIG)
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats == {"ok": 1, "empty": 0, "failed": 0}
    assert assets_state.load(m)["http://h/x.jpg"]["status"] == "ok"


def test_no_snapshot_and_empty_stay_terminal_on_download(tmp_path, monkeypatch):
    # Обратная сторона того же решения, и она тоже сознательная: `no_snapshot`
    # — честный ответ CDX «снимков нет», `empty` — тело есть, но содержимым
    # не является. Оба перестают быть верными только со временем, а не при
    # повторе того же прогона, и оба стоят CDX-запросов: 5106 бессмысленных
    # обращений за прогон — это ровно то, за что банят. Пере-запрос этих
    # статусов — отдельная осознанная операция, не поведение по умолчанию.
    conn = _seeded(tmp_path, "http://h/no.jpg", "http://h/empty.jpg", "http://h/ok.jpg")
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/no.jpg", None, "no_snapshot")
    assets_state.record(m, "http://h/empty.jpg", None, "empty")
    assets_state.record(m, "http://h/ok.jpg", "host/abc.jpg", "ok")
    calls = []
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: calls.append(url) or [])
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot",
                         lambda ts, url, **kw: calls.append(url) or PNG_SIG)
    stats = fetch_assets.download(conn, m, tmp_path / "assets")
    assert stats == {"ok": 0, "empty": 0, "failed": 0}
    assert calls == []          # ни одного обращения: целей нет вовсе
    statuses = {u: r["status"] for u, r in assets_state.load(m).items()}
    assert statuses == {"http://h/no.jpg": "no_snapshot", "http://h/empty.jpg": "empty",
                         "http://h/ok.jpg": "ok"}


def test_index_asks_cdx_once_per_url_and_never_again(tmp_path, monkeypatch):
    # Цель `index` — только адреса, о которых манифест не знает ВООБЩЕ.
    # Повторная индексация уже размеченного адреса (в т.ч. `no_snapshot`) не
    # ходит в CDX: иначе каждый прогон стоил бы 5007 запросов метаданных.
    conn = _seeded(tmp_path, "http://h/x.jpg")
    m = tmp_path / "m.jsonl"
    calls = []
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_find_snapshot",
                         lambda url, **kw: calls.append(url) or None)
    assert fetch_assets.index_pending(conn, m) == {"pending": 0, "no_snapshot": 1}
    assert fetch_assets.index_pending(conn, m) == {"pending": 0, "no_snapshot": 0}
    assert calls == ["http://h/x.jpg"]


def test_the_two_downloaders_agree_on_which_statuses_are_terminal():
    # Прямое расхождение C1: `fetch_site` перезапрашивает `failed`, а
    # `fetch_assets` его не перезапрашивал. Утверждение стоит на обоих
    # модулях разом, чтобы следующая правка одного из них не развела их
    # снова молча.
    from pipeline import fetch_site
    assert "failed" in fetch_assets.RETRY_ON_DOWNLOAD
    assert fetch_assets.TERMINAL_STATUSES == ("ok", "no_snapshot", "empty")
    assert fetch_site.TERMINAL_STATUSES == ("ok", "empty")


def test_terminal_statuses_are_retried_only_with_an_explicit_flag(tmp_path, monkeypatch):
    # Уточнение лида к Ruling 33: перезапрос терминальных статусов — только по
    # явному флагу, а не сменой умолчания. Обратная неприятность не менее
    # реальна, чем исходная: молча переспрашивать `no_snapshot` каждый прогон
    # — это 5007 обращений к архиву впустую.
    conn = _seeded(tmp_path, "http://h/no.jpg", "http://h/empty.jpg")
    m = tmp_path / "m.jsonl"
    assets_state.record(m, "http://h/no.jpg", None, "no_snapshot")
    assets_state.record(m, "http://h/empty.jpg", None, "empty")
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_find_snapshot",
                         lambda url, **kw: ("20200101000000", url))
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_snapshots", lambda url, **kw: [("20150101", url)])
    monkeypatch.setattr(fetch_assets.fetcher, "fetch_snapshot", lambda ts, url, **kw: PNG_SIG)

    # без флага — целей нет ни на одном шаге
    assert fetch_assets.index_pending(conn, m) == {"pending": 0, "no_snapshot": 0}
    assert fetch_assets.download(conn, m, tmp_path / "assets") == {"ok": 0, "empty": 0, "failed": 0}

    # `no_snapshot` перезапрашивается на шаге index, `empty` — на download,
    # и каждый только своим флагом, а не «за компанию».
    assert fetch_assets.index_pending(conn, m, retry=("no_snapshot",)) == {"pending": 1, "no_snapshot": 0}
    assert fetch_assets.download(conn, m, tmp_path / "assets", retry=("empty",))["ok"] == 2


def test_retry_flag_rejects_an_unknown_status(tmp_path):
    # Опечатка в флаге не должна выглядеть как «нового в архиве не появилось».
    conn = _seeded(tmp_path, "http://h/x.jpg")
    m = tmp_path / "m.jsonl"
    import pytest
    with pytest.raises(ValueError, match="нельзя перезапросить статус"):
        fetch_assets.download(conn, m, tmp_path / "assets", retry=("ok",))
    with pytest.raises(ValueError, match="нельзя перезапросить статус"):
        fetch_assets.index_pending(conn, m, retry=("нет-такого",))


def test_retry_flag_rejects_a_status_that_means_nothing_for_this_step(tmp_path, monkeypatch):
    # A6 ре-ревью (Ruling 44): `download --retry no_snapshot` давал те же 10
    # целей, что и без флага, и молчал — «целей нет» читалось как «в архиве
    # ничего нового». Тот же класс молчаливого no-op, что исходный C1.
    conn = _seeded(tmp_path, "http://h/x.jpg")
    m = tmp_path / "m.jsonl"
    import pytest
    with pytest.raises(ValueError, match="нельзя перезапросить на шаге `download`"):
        fetch_assets.download(conn, m, tmp_path / "assets", retry=("no_snapshot",))
    with pytest.raises(ValueError, match="нельзя перезапросить на шаге `index`"):
        fetch_assets.index_pending(conn, m, retry=("empty",))
    # А на своём шаге тот же флаг принимается молча и работает. (Подмена CDX
    # обязательна: адрес и без флага — цель индексации, потому что манифест о
    # нём не знает вовсе. Забыл подменить в первой версии этого теста —
    # заграждение сети из conftest поймало вызов на `socket.connect`, что
    # заодно и подтвердило, что второй рубеж работает.)
    monkeypatch.setattr(fetch_assets.fetcher, "cdx_find_snapshot", lambda url, **kw: None)
    assert fetch_assets.index_pending(conn, m, retry=("no_snapshot",)) == {"pending": 0, "no_snapshot": 1}


def test_cli_reports_a_bad_retry_flag_with_exit_code(tmp_path, capsys):
    from pipeline import run
    rc = run.main(["assets", "download", "--db", str(tmp_path / "f.sqlite"),
                    "--assets-manifest", str(tmp_path / "m.jsonl"),
                    "--assets-root", str(tmp_path / "a"), "--retry", "ok"])
    assert rc == 2
    assert "нельзя перезапросить статус" in capsys.readouterr().out
