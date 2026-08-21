"""Единое правило классификации вложений: контент против интерфейсного хрома.

До этого модуля правило жило в двух местах и отвечало на два разных
вопроса об одной сущности: `ingest._classify_attachment` решал «свой адрес
или чужой хост», а `mirror._is_interface_chrome` — «рендерить или молчать».
Загрузчику фазы добора пришлось бы завести третью копию, и разошлись бы
они молча (скачали бы 20 тысяч смайлов либо не скачали 85 нужных
`show_file`). Теперь правило одно и живёт здесь; загрузчик пишет по нему
`attachments.kind`/`attachments.status`, генератор по нему же решает, что
показывать, фаза добора — что качать.

Три вида (`kind`):

- `chrome` — смайлы и иконки, вшитые в шаблон движка (`bitrix/images`,
  `images/smiley_icons`) на своём же адресе. На корпусе 20416 из 20764
  «локальных» строк. Файла у них никогда не было и не будет: это не потеря
  контента, а разметка интерфейса. Не качать, не рендерить, не помечать
  утратой.
- `local` — вложение самого форума без собственного файла в архиве:
  `index.php?t=getfile&id=N` (253), `.../forum.interface/show_file.php?fid=N`
  (85, тот же механизм раздачи — см. Ruling 23), `upload/WEB-002/thumbnails`
  (7) и прочее (3). Итого 348 — это и есть те вложения, которые фаза добора
  обязана увидеть.
- `external_image` — картинка на чужом хосте (8612): фотохостинги, чужие
  форумы. Её добирают из веба/Wayback.

`status` при загрузке: `skip` для хрома (качать нечего) и `pending` для
всего остального (файла нет — значит ждёт добора). Прежняя семантика
(`ok` для всего локального) означала бы, что естественный запрос фазы
добора `WHERE status='pending'` молча пропустит все 348 своих вложений —
дефект I4 итогового ревью.
"""
import hashlib
import re
import urllib.parse
from pathlib import Path
from urllib.parse import urlparse

KIND_CHROME = "chrome"
KIND_LOCAL = "local"
KIND_EXTERNAL = "external_image"

# Маркеры интерфейсного хрома. Проверяются ТОЛЬКО для своих адресов:
# чужой хост с похожим путём — всё равно внешняя картинка.
# ВАЖНО: `bitrix/components` сюда не входит — это раздача вложений
# (`forum.interface/show_file.php?fid=N`), то есть контент (Ruling 23).
CHROME_MARKERS = ("bitrix/images", "images/smiley_icons")


def _is_own_host(url: str) -> bool:
    """Свой адрес — тот, у которого нет чужого хоста.

    Пустой `netloc` — относительный путь (с ведущим слэшем или без, оба
    встречаются в разметке), он всегда указывает на сам форум. Явный
    `subaru-faq` в хосте — тоже свой. `urlparse("//host/x").netloc`
    возвращает хост и без схемы, поэтому протокол-относительные адреса
    ловятся тем же условием, что и `http(s)://`.
    """
    netloc = urlparse(url or "").netloc
    return not netloc or "subaru-faq" in netloc


def classify(url: str) -> str:
    """`chrome` / `local` / `external_image` по адресу вложения."""
    url = url or ""
    if not _is_own_host(url):
        return KIND_EXTERNAL
    if any(marker in url for marker in CHROME_MARKERS):
        return KIND_CHROME
    return KIND_LOCAL


def initial_status(kind: str) -> str:
    """Статус строки вложения в момент загрузки: файла нет ни у одной."""
    return "skip" if kind == KIND_CHROME else "pending"


def is_content(kind: str) -> bool:
    """True — вложение содержательное: его показывают в заметке (вставкой
    или пометкой об утрате) и его добирает фаза 2. False — хром движка.
    """
    return kind != KIND_CHROME


def canonical_key(url: str) -> str:
    """Ключ «это тот же ресурс?» — без схемы, без порта, без `www.`, хост в
    нижнем регистре, путь И ЗАПРОС раскодированы (percent-decoding).

    Живёт здесь, а не в `fetcher`, потому что отвечает на вопрос про АДРЕС, а
    не про сеть, и нужен обоим: `fetcher.cdx_find_snapshot` сверяет им
    кандидатов CDX с нашим URL, `asset_name` строит по нему имя файла.
    `fetcher._canonical_key` оставлен псевдонимом — на него ссылаются
    докстринги и тесты.

    ЗАПРОС ВХОДИТ В КЛЮЧ ОБЯЗАТЕЛЬНО. Вложения форума раздаются адресами
    вида `.../forum.interface/show_file.php?fid=N` и `index.php?t=getfile&
    id=N`: путь у них ОДИН И ТОТ ЖЕ, различает файлы только номер в запросе.
    Замер на боевой базе: **50** разных скачанных файлов делят один путь
    `bitrix/components/bitrix/forum.interface/show_file.php` — 50 адресов,
    50 файлов, 50 различных по содержимому. Ключ без запроса схлопнул бы их
    в одно имя и подставил одну картинку вместо пятидесяти разных, молча.
    Цифра сверена дважды и с двух сторон: прямым замером по базе и
    раскладкой переименований Ruling 38 (`.php`→`.jpg` 48 плюс `.php`→`.gif`
    2 — ровно 50). В первой редакции этого докстринга стояло «49» — ошибка
    счёта, найдена ре-ревью (Ruling 42).
    """
    parts = urllib.parse.urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = urllib.parse.unquote(parts.path or "")
    query = urllib.parse.unquote(parts.query or "")
    key = host + path
    if query:
        key += "?" + query
    return key


# Байтовые сигнатуры (magic bytes) форматов, которые реально встречаются в
# контенте форума: картинки фотохостингов и документы, приклеенные к постам.
# ОДНА таблица на весь проект — до неё знание о сигнатурах жило в двух местах
# и уже разошлось (мёртвая константа `_IMAGE_SIGS` в `fetch_assets` не знала
# про WEBP, а живой код знал — M5 итогового ревью Ф2).
#
# Третий элемент — расширение, которое ОДНОЗНАЧНО следует из сигнатуры.
# `None` там, где сигнатура определяет контейнер, а не тип: `PK\x03\x04` это
# и .zip, и .docx/.xlsx/.pptx, а OLE2 — и .doc, и .xls, и .ppt. Угадывать
# в таких случаях нельзя: молча назвать неизвестное `.docx` хуже, чем
# оставить расширение из адреса.
_SIGNATURES = (
    (lambda d: d[:3] == b"\xff\xd8\xff", "image", ".jpg"),
    (lambda d: d[:8] == b"\x89PNG\r\n\x1a\n", "image", ".png"),
    (lambda d: d[:6] in (b"GIF87a", b"GIF89a"), "image", ".gif"),
    (lambda d: d[:2] == b"BM", "image", ".bmp"),
    (lambda d: d[:4] == b"RIFF" and d[8:12] == b"WEBP", "image", ".webp"),
    (lambda d: d[:4] == b"%PDF", "document", ".pdf"),
    (lambda d: d[:4] == b"PK\x03\x04", "document", None),
    (lambda d: d[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "document", None),
    (lambda d: d[:6] == b"Rar!\x1a\x07", "document", ".rar"),
    (lambda d: d[:6] == b"7z\xbc\xaf\x27\x1c", "document", ".7z"),
    (lambda d: d[:2] == b"\x1f\x8b", "document", ".gz"),
)


def sniff(data: bytes) -> tuple[str, str | None] | None:
    """`("image"|"document", расширение или None)` по началу данных.

    `None` — ни одна известная сигнатура не совпала.
    """
    data = data or b""
    for matches, kind, ext in _SIGNATURES:
        if matches(data):
            return kind, ext
    return None


def sniff_extension(data: bytes) -> str | None:
    """Расширение, ОДНОЗНАЧНО следующее из байтов, или `None`."""
    found = sniff(data)
    return found[1] if found else None


def is_image(data: bytes) -> bool:
    """Валидная сигнатура известного графического формата."""
    found = sniff(data)
    return bool(found) and found[0] == "image"


def is_document(data: bytes) -> bool:
    """Валидная сигнатура распространённого офисного/архивного формата:
    PDF, OLE2 (.doc/.xls), OpenXML и обычный zip, RAR, 7z, gzip.
    """
    found = sniff(data)
    return bool(found) and found[0] == "document"


def asset_name(url: str, data: bytes | None = None) -> str:
    """Имя файла вложения в зеркале: `<sha1(canonical_key)[:16]><ext>`.

    `data` (начало файла, если он на руках) — источник РАСШИРЕНИЯ, и он
    главнее адреса (Ruling 38). Причина: 348 вложений форума раздаются
    адресами `show_file.php?fid=N` и `index.php?t=getfile&id=N`, где
    расширения нет вовсе или оно врёт про тип. Имя `<hash>.php` для JPEG
    механически целое — `check_mirror` видит файл, вставка не битая, — но
    Obsidian такую вставку картинкой НЕ покажет: 50 настоящих фотографий
    просто не существуют для читателя, а вики делается для чтения.
    Байты не опознались (или сигнатура определяет только контейнер) ->
    расширение берётся из пути, как раньше.

    ОДНА функция на все три раздела зеркала (форум, FAQ, блоги) — до этой
    правки их было две с одинаковым видом имени, но считавшихся от ПОЛНОГО
    URL (`fetch_assets.local_name` и `mirror_faq._local_asset_name`, дефект
    M4 и отложенный пункт 6 итогового ревью Ф2). Из-за хоста и
    percent-encoding в хэше один и тот же файл получал разные имена в
    разных разделах: 90 картинок, вставленных и в FAQ, и в блоги, лежали в
    двух каталогах под двумя именами, а при доборе недостающих 248 картинок
    через `fetch_assets` тот же файл получил бы третье имя.

    Расширение из пути берётся не из запроса и только если похоже на
    расширение; иначе `.bin`.
    """
    ext = sniff_extension(data) if data else None
    if not ext:
        parts = urllib.parse.urlsplit(url or "")
        ext = Path(urllib.parse.unquote(parts.path or "")).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext or ""):
            ext = ".bin"
    return hashlib.sha1(canonical_key(url).encode("utf-8")).hexdigest()[:16] + ext


# Имя, которое даёт `asset_name`, и только оно: по этому виду `write_all`
# отличает файлы, которые положил сам, от чужих файлов в каталоге `assets/`
# (уборка сирот удаляет только свои — см. `mirror.prune_assets`).
ASSET_NAME_RE = re.compile(r"^[0-9a-f]{16}\.[a-z0-9]{1,5}$")
