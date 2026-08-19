"""Добор внешних картинок и документов из Wayback в два шага.

Сперва индексация: у скольких URL вообще есть снимок в CDX. Замер на выборке
60 URL дал 15% выживаемости, то есть из 6008 внешних адресов вернётся порядка
900 — качать тела по всем 6008 бессмысленно и дорого (каждое тело — отдельный
запрос к архиву). Индексация не тянет тела вовсе, поэтому её можно позволить
себе на всём списке.

Один вызов CDX на URL за весь шаг. И на индексации, и на скачивании — ровно
один `fetcher.cdx_snapshots(url)`. На тысячах адресов, где снимка нет, второй
вызов "просто чтобы уточнить исход" удвоил бы нагрузку на архив без всякой
пользы — ровно то, за что банят. Различить на шаге скачивания "снимок был, но
всё содержимое пустое" от "ни один снимок не скачался" можно и по уже
полученному списку снимков плюс флагу, скачалось ли хоть одно тело — второй
запрос для этого не нужен.

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
import re
import urllib.parse
from pathlib import Path

from pipeline import assets_state, attachments, fetcher

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


def _targets(conn, manifest: Path, want: str, limit: int | None):
    """URL-адреса и их kind, ожидающие данного шага (index/download).

    Состояние — то, что знает манифест (`assets_state.load`), а НЕ колонка
    `attachments.status`: она не трогается до самого конца прогона (см.
    `sync_to_db`, вызываемый run.py один раз по завершении), поэтому её
    значение здесь ничего не скажет о том, что уже сделано на этом прогоне.
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
        elif want == "download" and state == "pending":
            out.append((url, kind))
    return out[:limit] if limit else out


def index_pending(conn, manifest: Path, limit: int | None = None) -> dict[str, int]:
    """Шаг 1: у скольких URL в CDX вообще есть снимок. Тела не тянет."""
    stats = {"pending": 0, "no_snapshot": 0}
    pacer = fetcher.TokenBucketPacer()
    for url, _kind in _targets(conn, manifest, "index", limit):
        snaps = fetcher.cdx_snapshots(url)
        if snaps:
            assets_state.record(manifest, url, None, "pending", note=snaps[0][0])
            stats["pending"] += 1
            pacer.note(True)
        else:
            assets_state.record(manifest, url, None, "no_snapshot")
            stats["no_snapshot"] += 1
            pacer.note(False)
        pacer.wait()
    return stats


def download(conn, manifest: Path, assets_root: Path, limit: int | None = None) -> dict[str, int]:
    """Шаг 2: качает тело только тем URL, у которых индексация нашла снимок.

    `snaps` запрашивается у CDX РОВНО ОДИН РАЗ на URL (см. docstring
    модуля) — дальше перебираются уже полученные снимки, от свежего к
    старому, пока не найдётся снимок с настоящим содержимым.
    """
    stats = {"ok": 0, "empty": 0, "failed": 0}
    pacer = fetcher.TokenBucketPacer()
    for url, kind in _targets(conn, manifest, "download", limit):
        probe = _content_probe(kind)
        snaps = fetcher.cdx_snapshots(url)          # единственный вызов CDX на этот URL
        data = None
        saw_content = False   # хоть одно тело скачалось, но не прошло проверку содержимого
        for ts, orig in snaps:
            candidate = fetcher.fetch_snapshot(ts, orig)
            if candidate is None:
                continue
            if fetcher.looks_empty_binary(candidate, content_probe=probe) is not None:
                saw_content = True
                continue
            data = candidate
            break
        if data is None:
            # "empty" — было хоть одно тело, но содержимое не подтвердилось;
            # "failed" — сеть не отдала ни одного тела (или снимков вдруг не
            # оказалось на этом прогоне) — это про сеть, а не про содержимое.
            reason = "empty" if saw_content else "failed"
            assets_state.record(manifest, url, None, reason)
            stats[reason] += 1
            pacer.note(False)
        else:
            rel = local_name(url)
            dst = Path(assets_root) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            assets_state.record(manifest, url, rel, "ok")
            stats["ok"] += 1
            pacer.note(True)
        pacer.wait()
    return stats
