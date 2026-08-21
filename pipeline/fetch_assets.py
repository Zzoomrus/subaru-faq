"""Добор внешних картинок и документов из Wayback в два шага.

Сперва индексация: у скольких URL вообще есть снимок в CDX. Индексация не
тянет тела вовсе, поэтому её можно позволить себе на всём списке (6600
адресов на боевой базе, не 6008 — см. отчёт задачи 3).

## Индексация: `matchType=prefix` по URL, а не `matchType=domain` по хосту

Первая версия индексации звала `fetcher.cdx_snapshots` (поточечный
`matchType=exact`) по одному на каждый URL — живой прогон на сервере
показал ~20 с/URL (десятки часов на весь список вместо обещанных 40 минут).
Ревью лида предложило группировать адреса по хосту и спрашивать хост
целиком (`matchType=domain`, замер лида — 2,6 с на 20 тыс. строк) — но живая
проверка этого подхода на боевых хостах (задача 3, живая правка) нашла
серьёзную проблему: у нескольких САМЫХ КРУПНЫХ хостов корпуса
(`s019.radikal.ru`, `img-fotki.yandex.ru` и однотипные им шардовые
фотохостинги) домен целиком не укладывается даже в 100 тыс. строк (5
страниц по 20000, всё усечено) — это чужая история всего хостинга, а не
только наших адресов, и качать её целиком ради десятков-сотен наших URL
вышло бы дороже, а не дешевле.

Вместо группировки по хосту — `fetcher.cdx_find_snapshot(url)`:
`matchType=prefix` **по самому нашему URL** (не по хосту). Он остаётся узким
(конкретный файл, а не вся история хоста) и при этом быстрым: замер на
живых данных — 2-5 с/URL против 10-50 с у `matchType=exact` на тех же
адресах (см. отчёт задачи 3, "Живая проверка сопоставления" и "matchType=
prefix vs exact"). Сопоставление найденного с нашим URL — не ручная
нормализация поверх ответа CDX (архив уже канонизирует схему/`www.`/регистр
хоста при самом поиске — подтверждено живым запросом с намеренно
несовпадающими вариантами), а сравнение `fetcher._canonical_key` на
РАВЕНСТВО — защита именно от обратного риска префиксного поиска: он может
задеть чужой ДЛИННЕЕ ресурс с тем же началом ключа.

## Один вызов CDX на URL за весь шаг скачивания — и часто вообще ноль

`download()` сперва пробует уже сохранённую индексацией метку снимка через
`fetcher.fetch_snapshot` напрямую — БЕЗ обращения к CDX вовсе. Только если
этот снимок оказался пустышкой или не отдался, запрашивается полный список
альтернатив (`fetcher.cdx_snapshots`, дорогой `matchType=exact`) — и то один
раз. На тысячах адресов, где сохранённый снимок и так рабочий, лишний
CDX-запрос удвоил бы нагрузку на архив без всякой пользы — ровно то, за что
банят.

Признак содержимого (что значит "пустышка") передаёт КАЖДЫЙ вызов сам —
`fetcher.looks_empty_binary` больше не знает про антибот-маркер CleanTalk
(см. docstring `fetcher.py`): виджет стоит в шаблоне доброй трети обычных
страниц сайта, и решение по нему отбраковало бы треть настоящего контента.
Для `external_image` (чужой хост, почти всегда фотография — см.
`attachments.py`) признак содержимого — валидная сигнатура известного
графического формата: `_looks_like_image`.

Для `local` (свои вложения форума: `getfile?id=N`, `show_file.php?fid=N`) тип
файла НЕЛЬЗЯ определить по URL — расширения там нет, только числовой id.
Это могут быть как картинки, так и документы, которые люди прикладывали к
постам (за 348 таких вложений реальный тип известен только по байтам самого
файла). Поэтому признак содержимого для `local` — валидная сигнатура ЛЮБОГО
известного бинарного формата: картинки (`_looks_like_image`) ИЛИ документа
(`_looks_like_document`: PDF, ZIP-контейнер — docx/xlsx/pptx/rar-совместимый
zip, старый OLE2 — doc/xls, RAR, 7z, gzip). Если сигнатура не совпала ни с
одним известным форматом, тело считается пустышкой: отличить редкий, но
настоящий формат от антибот-заглушки/страницы "not archived" по байтам
надёжно нельзя, а ограничение фазы прямое — "ни одной битой картинки в вики",
то есть в спорном случае лучше явная пометка потери, чем непроверенный блоб
на диске.
"""
import hashlib
import logging
import re
import urllib.parse
from pathlib import Path

from pipeline import assets_state, attachments, fetcher

_LOG = logging.getLogger(__name__)
# Индексация идёт ~40 минут, скачивание — часы, оба без вложений/файлов на
# каждом шаге, кроме самого последнего. Без периодической метки прогресса
# лог под nohup за это время не наполнился бы вовсе, и наблюдающий не сможет
# отличить «работает» от «висит» до самого конца прогона.
_PROGRESS_EVERY = 50

# Ровно те виды вложений, у которых `attachments.is_content(kind)` истинно и
# файла в архиве нет (см. `attachments.py`): чужие картинки и свои вложения
# форума без сырого файла. `chrome` сюда не входит — качать нечего.
CONTENT_KINDS = (attachments.KIND_EXTERNAL, attachments.KIND_LOCAL)

# Сигнатуры (magic bytes) графических форматов, встречающихся в контенте
# форума (см. распределение расширений `external_image`: jpg/gif/png/jpeg).
_IMAGE_SIGS = (
    b"\xff\xd8\xff",              # JPEG
    b"\x89PNG\r\n\x1a\n",         # PNG
    b"GIF87a",
    b"GIF89a",
    b"BM",                        # BMP
)


def _looks_like_image(data: bytes) -> bool:
    """Валидная сигнатура известного графического формата в начале данных."""
    if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:2] == b"BM":
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def _looks_like_document(data: bytes) -> bool:
    """Валидная сигнатура распространённого офисного/архивного формата.

    Покрывает то, что реально приклеивают к форумным постам: PDF, старые
    Office-документы (OLE2: .doc/.xls), новые Office/OpenXML и обычный zip
    (общий ZIP-заголовок PK\\x03\\x04), RAR, 7z, gzip.
    """
    if data[:4] == b"%PDF":
        return True
    if data[:4] == b"PK\x03\x04":
        return True
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return True
    if data[:6] in (b"Rar!\x1a\x07",):
        return True
    if data[:6] == b"7z\xbc\xaf\x27\x1c":
        return True
    if data[:2] == b"\x1f\x8b":
        return True
    return False


def _content_probe(kind: str):
    """Признак содержимого для `looks_empty_binary`, свой для каждого kind."""
    if kind == attachments.KIND_LOCAL:
        return lambda data: _looks_like_image(data) or _looks_like_document(data)
    return _looks_like_image


def local_name(url: str) -> str:
    """Путь внутри assets/: хост + хэш пути + исходное расширение."""
    parts = urllib.parse.urlsplit(url)
    host = re.sub(r"[^a-z0-9.-]", "_", parts.netloc.lower()) or "nohost"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    ext = Path(urllib.parse.unquote(parts.path)).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext or ""):
        ext = ".bin"
    return "%s/%s%s" % (host, digest, ext)


# Статусы манифеста, которые повторный прогон `download` ПЕРЕзапрашивает, и
# те, которые для него терминальны (дефект C1 итогового ревью Ф2, Ruling 33).
#
# `failed` — «сеть не отдала ни одного тела»: это утверждение о ПРОГОНЕ, а не
# об архиве, и повторять его правильно. Ровно так уже устроен добор страниц
# сайта (`fetch_site.fetch_all` фильтрует `status not in ("ok", "empty")`) —
# два модуля решали одну задачу противоположно, и ни один отчёт этого не
# отмечал. До правки `failed` был терминальным, то есть 10 адресов боевого
# манифеста не пробовали больше НИКОГДА, а повторный прогон возвращал
# `{'ok': 0, ...}` и выглядел как успех.
#
# `no_snapshot` (5007 адресов) и `empty` (99) остаются терминальными
# СОЗНАТЕЛЬНО: первое — честный ответ CDX «снимков нет», второе — тело
# скачалось, но содержимым не является. Оба перестают быть верными только со
# временем (архив набирает новые снимки), а не при повторе того же прогона
# через час, и оба стоят по одному-двум CDX-запросам на адрес: 5106
# бессмысленных запросов на каждый прогон — это ровно то, за что банят.
# Пере-запрос этих двух — отдельная осознанная операция «а не появилось ли в
# архиве нового», её вводить вместе с явным флагом, а не по умолчанию.
RETRY_ON_DOWNLOAD = ("pending", "failed")
TERMINAL_STATUSES = ("ok", "no_snapshot", "empty")


def _targets(conn, manifest: Path, want: str, limit: int | None):
    """URL-адреса и их kind, ожидающие данного шага (index/download).

    Состояние — то, что знает манифест (`assets_state.load`), а НЕ колонка
    `attachments.status`: она не трогается до самого конца прогона (см.
    `sync_to_db`, вызываемый run.py один раз по завершении), поэтому её
    значение здесь ничего не скажет о том, что уже сделано на этом прогоне.

    Цель шага `index` — только адреса, о которых манифест не знает ВООБЩЕ
    (`state is None`): один раз спросили CDX, получили ответ, записали. Цель
    шага `download` — `RETRY_ON_DOWNLOAD` (`pending` + `failed`), терминальны
    `TERMINAL_STATUSES`; какие именно и почему — в комментарии выше.
    """
    known = assets_state.load(manifest)
    sql = ("SELECT DISTINCT url, kind FROM attachments WHERE kind IN (%s) AND status <> 'skip'"
           % ",".join("?" * len(CONTENT_KINDS)))
    rows = conn.execute(sql, CONTENT_KINDS).fetchall()
    out = []
    for url, kind in rows:
        state = known.get(url, {}).get("status")
        if want == "index" and state is None:
            out.append((url, kind))
        elif want == "download" and state in RETRY_ON_DOWNLOAD:
            out.append((url, kind))
    return out[:limit] if limit else out


def index_pending(conn, manifest: Path, limit: int | None = None) -> dict[str, int]:
    """Шаг 1: у скольких URL в CDX вообще есть снимок. Тела не тянет.

    Использует `fetcher.cdx_find_snapshot` (`matchType=prefix` по самому
    URL) — см. docstring модуля про то, почему не поточечный `exact` и не
    хостовый `domain`. Найденная метка снимка (`ts`) сохраняется в манифест
    как есть — второй шаг (`download`) пробует её напрямую, без нового
    обращения к CDX.

    `pacer.note(True)` вызывается ВСЕГДА, независимо от того, нашёлся ли
    снимок. Замер на живом прогоне (VPS `bots`, 2026-08-19) показал: при
    ожидаемой выживаемости ~15-25% большинство ответов CDX — "снимков нет", и
    если бы это считалось неудачей пейсера (как при скачивании тела, где
    неудача — это про сеть), скользящий рейт быстро проваливался к 0 и держал
    паузу на потолке (10-19 с/запрос) почти весь прогон. Технически "снимков
    нет" — это ЧЕСТНЫЙ ответ архива, а не признак перегрузки; признак
    перегрузки (сетевые ошибки) уже обрабатывает свой backoff внутри
    `cdx_find_snapshot`/`_cdx_page` (retries с нарастающей паузой). Внешний
    пейсер здесь — это только вежливый интервал между запросами МЕТАДАННЫХ
    (CDX), а не тот же токен-бакет, что бережёт отдачу тел снимков (см.
    `global-constraints.md`: лимит "~2 стр/мин" — про отдачу страниц, к
    CDX-поиску не относится).
    """
    stats = {"pending": 0, "no_snapshot": 0}
    pacer = fetcher.TokenBucketPacer()
    targets = _targets(conn, manifest, "index", limit)
    total = len(targets)
    for i, (url, _kind) in enumerate(targets, 1):
        found = fetcher.cdx_find_snapshot(url)
        if found:
            ts, _original = found
            assets_state.record(manifest, url, None, "pending", note=ts)
            stats["pending"] += 1
        else:
            assets_state.record(manifest, url, None, "no_snapshot")
            stats["no_snapshot"] += 1
        pacer.note(True)
        if i % _PROGRESS_EVERY == 0 or i == total:
            _LOG.info("индексация: %d/%d — pending=%d no_snapshot=%d",
                       i, total, stats["pending"], stats["no_snapshot"])
        pacer.wait()
    return stats


def _try_candidates(candidates, probe):
    """Пробует снимки по очереди, пока не найдёт снимок, проходящий `probe`.

    Возвращает `(данные, saw_content)`: если ни один снимок не подошёл,
    `данные is None`, а `saw_content` истинно, если хоть одно тело реально
    скачалось, но не прошло проверку содержимого (нужно вызывающей стороне,
    чтобы отличить "empty" от "failed" без второго обращения к CDX).
    """
    saw_content = False
    for ts, orig in candidates:
        candidate = fetcher.fetch_snapshot(ts, orig)
        if candidate is None:
            continue
        if fetcher.looks_empty_binary(candidate, content_probe=probe) is not None:
            saw_content = True
            continue
        return candidate, saw_content
    return None, saw_content


def download(conn, manifest: Path, assets_root: Path, limit: int | None = None) -> dict[str, int]:
    """Шаг 2: качает тело только тем URL, у которых индексация нашла снимок.

    Сперва пробует метку снимка, СОХРАНЁННУЮ индексацией (`note` в манифесте)
    — напрямую через `fetch_snapshot`, без единого обращения к CDX. Только
    если этот снимок пустышка или не отдался, запрашивается полный список
    альтернатив (`fetcher.cdx_snapshots`, дорогой `matchType=exact`) — и то
    ОДИН раз (см. docstring модуля). На бóльшей части адресов, где
    сохранённый снимок и так рабочий, CDX не вызывается вовсе.

    Повторный прогон берёт `pending` и `failed`, не берёт `ok`,
    `no_snapshot` и `empty` (`RETRY_ON_DOWNLOAD`/`TERMINAL_STATUSES` — там же
    и обоснование). Отсюда прямое следствие, которое НЕЛЬЗЯ читать как факт
    об архиве: «повторный прогон нашёл ноль» на манифесте, где всё уже
    размечено, означает только «целей не осталось», а не «в Wayback этого
    нет». Проверять, не появилось ли в архиве новых снимков для 5106
    терминальных адресов, придётся отдельной осознанной операцией.
    """
    stats = {"ok": 0, "empty": 0, "failed": 0}
    pacer = fetcher.TokenBucketPacer()
    known = assets_state.load(manifest)
    targets = _targets(conn, manifest, "download", limit)
    total = len(targets)
    for i, (url, kind) in enumerate(targets, 1):
        probe = _content_probe(kind)
        saved_ts = known.get(url, {}).get("note") or None
        saw_content = False

        data = None
        if saved_ts:
            data, seen = _try_candidates([(saved_ts, url)], probe)
            saw_content = saw_content or seen
        if data is None:
            # Сохранённый снимок не сработал (или индексация его не нашла на
            # этом URL по какой-то причине) — теперь и только теперь просим у
            # CDX полный список альтернатив. Дорого, но редко: только на
            # пустышки/сбои сохранённого снимка, не на каждый URL подряд.
            data, seen = _try_candidates(fetcher.cdx_snapshots(url), probe)
            saw_content = saw_content or seen
        if data is None:
            # "empty" — было хоть одно тело, но содержимое не подтвердилось;
            # "failed" — сеть не отдала ни одного тела (или снимков вдруг не
            # оказалось на этом прогоне) — это про сеть, а не про содержимое.
            reason = "empty" if saw_content else "failed"
            assets_state.record(manifest, url, None, reason)
            stats[reason] += 1
            # Пейсер штрафует только СЕТЕВУЮ неудачу (failed), не пустышку по
            # содержимому (empty) — тело скачалось, значит сеть отработала;
            # пустышка не сеть подвела, ровно то же рассуждение, что уже
            # применено к "снимков нет" в index_pending (см. её докстринг).
            # Иначе череда пустышек подряд (а не сетевых сбоев) без причины
            # роняла бы темп скачивания до потолка паузы.
            pacer.note(reason != "failed")
        else:
            rel = local_name(url)
            dst = Path(assets_root) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            assets_state.record(manifest, url, rel, "ok")
            stats["ok"] += 1
            pacer.note(True)
        if i % _PROGRESS_EVERY == 0 or i == total:
            _LOG.info("скачивание: %d/%d — ok=%d empty=%d failed=%d",
                       i, total, stats["ok"], stats["empty"], stats["failed"])
        pacer.wait()
    return stats
