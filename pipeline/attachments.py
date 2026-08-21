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
import struct
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


# Размер картинки, при котором она не может быть содержимым поста. Порог
# ровно 2, а не «маленькая»: 1x1 — трекинг-пиксель, который фотохостинг
# отдаёт вместо удалённого файла (55 таких на корпусе), а настоящие мелкие
# картинки в постах — смайлы и иконки от 10 px, их отсекают другие правила
# (`CHROME_MARKERS`) или не отсекают сознательно (чужие смайлы, находка Б2
# ре-ревью). Всё, что между, трогать нельзя: «маленькая» не значит «пустая».
PLACEHOLDER_MAX_SIDE = 2


def image_size(data: bytes) -> tuple[int, int] | None:
    """`(ширина, высота)` из заголовка картинки или `None`, если не вышло.

    `None` — «не знаю», и вызывающий обязан трактовать это как «картинка
    настоящая»: пометить содержимое утраченным по незнанию хуже, чем
    пропустить заглушку (см. `looks_like_placeholder`). WEBP разобран только
    в простых формах (VP8X/VP8 ), lossless VP8L даёт `None` — на корпусе
    WEBP нет вовсе, а угадывать битовую упаковку ради нуля файлов незачем.
    """
    data = data or b""
    try:
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", data[16:24])
            return int(w), int(h)
        if data[:2] == b"BM":
            w, h = struct.unpack("<ii", data[18:26])
            return abs(w), abs(h)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            if data[12:16] == b"VP8X":
                return (1 + int.from_bytes(data[24:27], "little"),
                        1 + int.from_bytes(data[27:30], "little"))
            if data[12:16] == b"VP8 ":
                w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
                h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
                return w, h
            return None
        if data[:3] == b"\xff\xd8\xff":
            # Идём по маркерам до первого SOF — только он несёт размеры.
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD9:
                    i += 2
                    continue
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
            return None
    except (struct.error, IndexError):
        return None
    return None


def looks_like_placeholder(data: bytes) -> bool:
    """True — файл валиден как картинка, но картинкой поста быть не может.

    Единственный признак — сторона <= `PLACEHOLDER_MAX_SIDE`, и он выбран
    потому, что ОДНОЗНАЧЕН: изображение 1x1 не несёт содержимого ни при каких
    обстоятельствах. Находка Б1 ре-ревью: 57 из 1859 вставок боевой вики — это
    43-байтные 1x1 GIF (трекинг-пиксель `i.piccy.info`, который хостинг отдаёт
    вместо удалённого файла) и два 1x1 JPEG. Все механически целы: сигнатура
    валидна, файл существует, проверка целостности даёт четыре нуля, и они
    посчитаны внутри главной цифры фазы «1484 картинки возвращены». Читатель
    же видит пустоту без всякой пометки об утрате.

    Правило САМОСТОЯТЕЛЬНОЕ: сторона, и только сторона. Ни «43 байта», ни
    конкретный хэш в него не входят, хотя именно так выглядела найденная
    заглушка — размер и хэш это приметы ОДНОГО трекера, а сторона признак
    КЛАССА. Добор следующей фазы принесёт другой трекер, с другими байтами и
    другим размером файла, и правило обязано поймать и его.

    Чего этот признак НЕ ловит и ловить не должен: заглушки НОРМАЛЬНОГО
    размера — например баннер «изображение было удалено» 200x236. Отличить
    такую от настоящей фотографии по байтам нельзя, и «одни байты у многих
    адресов» тоже не годится как автоматическое правило: настоящая
    фотография, выложенная на нескольких шардах фотохостинга, даёт ровно ту
    же картину (проверено лидом снизу — при пороге «два адреса» в группы
    попадает настоящее фото 640x360 с двух шардов radikal.ru). Поэтому
    байт-идентичность остаётся ДИАГНОСТИКОЙ (`fetch_assets.sieve_report`
    перечисляет группы), а приговор конкретному файлу выносит человек и
    хранится он в `DECIDED_PLACEHOLDER_SHA256` — см. ниже.
    """
    if not is_image(data):
        return False
    size = image_size(data)
    if size is None:
        return False
    return min(size) <= PLACEHOLDER_MAX_SIDE


# ПРИГОВОРЫ КОНКРЕТНЫМ ФАЙЛАМ, вынесенные человеком глазами. Здесь хэш
# уместен именно потому, что он адресует один-единственный файл: это не
# правило класса (см. `looks_like_placeholder`), а список «вот эти байты —
# заглушка, решено». Автоматизировать нельзя: «одни байты у трёх адресов»
# накрыло бы и настоящую фотографию с нескольких шардов хостинга, и она молча
# исчезла бы из вики.
#
# Порядок пополнения списка: `run assets sieve` печатает группы
# байт-идентичных файлов (>= 3 адресов) с образцом пути -> человек ОТКРЫВАЕТ
# образец и смотрит -> если заглушка, её sha256 дописывается сюда с
# основанием.
DECIDED_PLACEHOLDER_SHA256 = {
    # Баннер «VFL.RU · Изображение было удалено · This image was deleted»,
    # 16 856 байт, 200x236. 18 адресов `images.vfl.ru` на корпусе Ф2.
    # Решение лида (Ruling 45), подтверждено визуально.
    "ec872606e266d9774a98276ab0d9e19a1155304c8180a879fedb7189ffde59f1":
        "баннер VFL.RU «изображение было удалено»",
}


def decided_placeholder(data: bytes) -> str | None:
    """Основание из `DECIDED_PLACEHOLDER_SHA256`, если байты уже осуждены."""
    return DECIDED_PLACEHOLDER_SHA256.get(hashlib.sha256(data or b"").hexdigest())


def is_placeholder(data: bytes) -> bool:
    """Заглушка по любому из двух оснований: правило класса (сторона) или
    вынесенный человеком приговор конкретным байтам. Именно это спрашивают
    просев и проверка содержимого при скачивании.
    """
    return looks_like_placeholder(data) or decided_placeholder(data) is not None
