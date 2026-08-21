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

# Сигнатуры форматов живут в ОДНОМ месте — `attachments._SIGNATURES` (там же
# и расширение, однозначно следующее из сигнатуры, Ruling 38). Здесь только
# тонкие псевдонимы: раньше знание о сигнатурах было продублировано, и копии
# уже разошлись — мёртвая константа `_IMAGE_SIGS` не знала про WEBP, а живая
# проверка знала (M5 итогового ревью Ф2).
_looks_like_image = attachments.is_image
_looks_like_document = attachments.is_document


def _is_real_image(data: bytes) -> bool:
    """Картинка, которая может быть содержимым поста.

    Валидной сигнатуры НЕДОСТАТОЧНО (находка Б1 ре-ревью): 43-байтный 1x1 GIF
    — валидный GIF, и фотохостинги отдают именно его вместо удалённого файла.
    57 таких файлов уже лежат в вики и посчитаны внутри цифры «1484 картинки
    возвращены». Без этой проверки добор Ф3 принёс бы тот же класс снова.
    """
    return _looks_like_image(data) and not attachments.looks_like_placeholder(data)


def _content_probe(kind: str):
    """Признак содержимого для `looks_empty_binary`, свой для каждого kind."""
    if kind == attachments.KIND_LOCAL:
        return lambda data: _is_real_image(data) or _looks_like_document(data)
    return _is_real_image


def local_name(url: str, data: bytes | None = None) -> str:
    """Путь внутри assets/: каталог по хосту + `attachments.asset_name`.

    Имя файла считает ОДНА общая функция на весь проект (`attachments.
    asset_name` — хэш канонического ключа адреса, дефект M4 итогового ревью
    Ф2): один и тот же файл обязан называться одинаково и здесь, и в трёх
    каталогах `assets/` зеркала, иначе при доборе недостающих картинок FAQ и
    блогов тот же файл получил бы третье имя.

    Каталог по хосту остаётся — он про раскладку на диске (`data/assets/
    files/`), а не про имя: несколько тысяч файлов в одном каталоге
    неудобно смотреть глазами, а хост сразу говорит, откуда файл. В зеркало
    копируется только имя (`assets/<имя>`), см. `mirror._copy_forum_asset`.

    `data` (скачанное тело) — источник расширения, и он главнее адреса
    (Ruling 38): у `show_file.php?fid=N` расширения в адресе нет вовсе, а у
    части адресов оно врёт про тип. Правило одно на весь проект, поэтому
    будущий добор кладёт файл с тем же расширением, какое даст зеркало.

    Уже скачанные файлы НЕ переименовываются: истина про добор — манифест
    (`assets_state`), в нём лежат старые пути, и они продолжают работать.
    Новая формула действует на то, что скачивается впредь.
    """
    parts = urllib.parse.urlsplit(url)
    host = re.sub(r"[^a-z0-9.-]", "_", parts.netloc.lower()) or "nohost"
    return "%s/%s" % (host, attachments.asset_name(url, data))


# Статусы манифеста и то, что с ними делает повторный прогон (дефект C1
# итогового ревью Ф2, Ruling 33 + уточнение лида).
#
# ПО УМОЛЧАНИЮ перезапрашивается ровно один статус — `failed`. Это
# утверждение о ПРОГОНЕ («сеть не отдала ни одного тела»), а не об архиве, и
# повторять его правильно. Ровно так уже устроен добор страниц сайта
# (`fetch_site.TERMINAL_STATUSES`) — до правки два модуля решали одну задачу
# противоположно, и ни один отчёт этого не отмечал: 10 адресов боевого
# манифеста не пробовали больше НИКОГДА, а повторный прогон возвращал
# `{'ok': 0, ...}` и выглядел как успех.
#
# `no_snapshot` (5007 адресов) и `empty` (99) ТЕРМИНАЛЬНЫ и по умолчанию не
# перезапрашиваются никогда. Обратная неприятность не менее реальна, чем
# исходная: молча переспрашивать `no_snapshot` на каждом прогоне — это 5007
# обращений к индексу впустую за прогон, ровно то, за что банят. Оба статуса
# перестают быть верными только СО ВРЕМЕНЕМ (архив набирает новые снимки), а
# не при повторе того же прогона через час, поэтому проверка «а не появилось
# ли в архиве нового» — отдельная осознанная операция под явным флагом
# (`--retry no_snapshot,empty` в `run.py`), а не смена умолчания.
#
# `ok` не перезапрашивается ни при каком флаге: файл уже лежит на диске, а
# манифест — истина про добор (см. `assets_state`).
RETRY_ON_DOWNLOAD = ("pending", "failed")
TERMINAL_STATUSES = ("ok", "no_snapshot", "empty")
# Что вообще разрешено передать флагом и на какой шаг это влияет:
# `no_snapshot` — на индексацию (спросить CDX заново), `empty` — на
# скачивание (тело было, но содержимым не признано; вдруг архив отдаёт
# другой снимок). Значение вне этого набора — ошибка вызова, не молчаливое
# игнорирование.
RETRIABLE_BY_FLAG = ("no_snapshot", "empty")


# Какой статус имеет смысл перезапрашивать на каком шаге. `no_snapshot` — это
# ответ CDX «снимков нет», проверить его можно только индексацией; `empty` —
# «тело скачалось, но содержимым не признано», это шаг скачивания.
_RETRY_STEP = {"no_snapshot": "index", "empty": "download"}


def _retry_targets(retry, want: str) -> tuple[set[str], set[str]]:
    """`retry` (набор статусов из флага) -> какие статусы добавить к целям
    шага `index` и шага `download`.

    Неизвестный статус — `ValueError`. Статус, не имеющий смысла для ЭТОГО
    шага, — тоже `ValueError`, а не тишина (находка A6 ре-ревью, Ruling 44):
    `assets download --retry no_snapshot` молча давал те же 10 целей, что и
    без флага, и ответ «целей 10» читался как «нового в архиве не
    появилось». Это ровно тот класс молчаливого no-op, который волна и
    чинила в C1, только этажом выше — попросили одно, получили другое, и
    никто не сказал. Цифра 5007 у человека в голове связана со скачиванием,
    так что ошибиться шагом — первое, что случится.
    """
    retry = set(retry or ())
    unknown = sorted(retry - set(RETRIABLE_BY_FLAG))
    if unknown:
        raise ValueError(
            "нельзя перезапросить статус(ы) %s: флагом разрешены только %s "
            "(`ok` не перезапрашивается никогда — файл уже на диске, "
            "`pending`/`failed` и так входят в цели по умолчанию)"
            % (", ".join(unknown), ", ".join(RETRIABLE_BY_FLAG)))
    wrong_step = sorted(st for st in retry if _RETRY_STEP[st] != want)
    if wrong_step:
        raise ValueError(
            "статус(ы) %s нельзя перезапросить на шаге `%s`: %s. Иначе прогон "
            "молча сделал бы не то, о чём просили, и «целей нет» прочиталось бы "
            "как «в архиве ничего нового»"
            % (", ".join(wrong_step), want,
               "; ".join("`%s` — только `assets %s`" % (st, _RETRY_STEP[st]) for st in wrong_step)))
    return ({"no_snapshot"} & retry), ({"empty"} & retry)


def _targets(conn, manifest: Path, want: str, limit: int | None, retry=()):
    """URL-адреса и их kind, ожидающие данного шага (index/download).

    Состояние — то, что знает манифест (`assets_state.load`), а НЕ колонка
    `attachments.status`: она не трогается до самого конца прогона (см.
    `sync_to_db`, вызываемый run.py один раз по завершении), поэтому её
    значение здесь ничего не скажет о том, что уже сделано на этом прогоне.

    Цель шага `index` — только адреса, о которых манифест не знает ВООБЩЕ
    (`state is None`): один раз спросили CDX, получили ответ, записали. Цель
    шага `download` — `RETRY_ON_DOWNLOAD` (`pending` + `failed`), терминальны
    `TERMINAL_STATUSES`; какие именно и почему — в комментарии выше.

    `retry` — статусы, которые вызывающий ЯВНО попросил перезапросить
    (`RETRIABLE_BY_FLAG`); без него терминальные статусы не попадают в цели
    ни на одном шаге.
    """
    retry_index, retry_download = _retry_targets(retry, want)
    known = assets_state.load(manifest)
    sql = ("SELECT DISTINCT url, kind FROM attachments WHERE kind IN (%s) AND status <> 'skip'"
           % ",".join("?" * len(CONTENT_KINDS)))
    rows = conn.execute(sql, CONTENT_KINDS).fetchall()
    out = []
    for url, kind in rows:
        state = known.get(url, {}).get("status")
        if want == "index" and (state is None or state in retry_index):
            out.append((url, kind))
        elif want == "download" and (state in RETRY_ON_DOWNLOAD or state in retry_download):
            out.append((url, kind))
    return out[:limit] if limit else out


def index_pending(conn, manifest: Path, limit: int | None = None, retry=()) -> dict[str, int]:
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
    targets = _targets(conn, manifest, "index", limit, retry=retry)
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


def download(conn, manifest: Path, assets_root: Path, limit: int | None = None,
              retry=()) -> dict[str, int]:
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
    нет». Проверить, не появилось ли в архиве нового, можно явным флагом
    (`--retry empty` / `--retry no_snapshot` — тот самый «осознанный
    прогон», см. `RETRIABLE_BY_FLAG`), и это стоит 5106 обращений к архиву,
    поэтому не делается само.
    """
    stats = {"ok": 0, "empty": 0, "failed": 0}
    pacer = fetcher.TokenBucketPacer()
    known = assets_state.load(manifest)
    targets = _targets(conn, manifest, "download", limit, retry=retry)
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
            rel = local_name(url, data)
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


def sieve_report(conn, manifest: Path, assets_root: Path) -> dict:
    """Просев уже скачанного: что из него не может быть картинкой поста.

    Читает только диск — ни сети, ни CDX. Возвращает два РАЗНЫХ по природе
    списка, и это главное в устройстве функции (распоряжение лида, Ruling 45):

    - `placeholders` — адреса, у которых файл валиден как картинка, но сторона
      <= 2 px. Признак ОДНОЗНАЧЕН (1x1 не несёт содержимого никогда), поэтому
      их можно метить машинально;
    - `identical_groups` — группы байт-идентичных файлов у ТРЁХ и более разных
      адресов, не попавшие в первый список. Признак НЕОДНОЗНАЧЕН: одна и та же
      настоящая фотография вполне могла лежать по трём адресам. Такие группы
      функция только перечисляет (размер, число адресов, образец пути) —
      решение по каждой принимает человек, глядя на картинку.

    Порог «три и более» — из находки Б1: 18 байт-идентичных файлов 200x236 с
    `images.vfl.ru` оказались баннером «изображение было удалено», и увидеть
    это можно было только глазами.
    """
    known = assets_state.load(manifest)
    root = Path(assets_root)
    placeholders: list[dict] = []
    by_digest: dict[str, list[dict]] = {}
    for url, rec in sorted(known.items()):
        if rec.get("status") != "ok" or not rec.get("path"):
            continue
        path = root / rec["path"]
        if not path.exists():
            continue
        data = path.read_bytes()
        item = {"url": url, "path": rec["path"], "bytes": len(data),
                "size": attachments.image_size(data)}
        if attachments.looks_like_placeholder(data):
            placeholders.append(item)
            continue
        by_digest.setdefault(hashlib.sha1(data).hexdigest(), []).append(item)
    groups = [{"bytes": items[0]["bytes"], "size": items[0]["size"], "urls": len(items),
               "sample": items[0]["path"], "sample_url": items[0]["url"]}
              for items in by_digest.values() if len(items) >= 3]
    groups.sort(key=lambda g: -g["urls"])
    return {"placeholders": placeholders, "identical_groups": groups}


def mark_empty(manifest: Path, urls) -> int:
    """Пометить адреса как `empty` в манифесте добора.

    `empty` — уже существующий статус «тело скачалось, но содержимым не
    является», и он ровно про этот случай; заводить новый («заглушка») значит
    учить понимать его `sync_to_db`, `_targets`, отчёты и человека, не получая
    ничего: дальнейшая судьба у них одна и та же — честная пометка об утрате в
    заметке. Статус терминальный и перезапрашивается только явным
    `--retry empty` (см. `RETRIABLE_BY_FLAG`), то есть повторный прогон не
    станет качать их снова.
    """
    n = 0
    for url in urls:
        assets_state.record(manifest, url, None, "empty", note="заглушка хостинга")
        n += 1
    return n
