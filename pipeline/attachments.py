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
    Замер на боевой базе: 49 разных скачанных файлов делят один путь
    `bitrix/components/bitrix/forum.interface/show_file.php` — ключ без
    запроса схлопнул бы их в один и подставил одну картинку вместо
    сорока девяти разных, молча (см. отчёт волны правок, пункт 5).
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


def asset_name(url: str) -> str:
    """Имя файла вложения в зеркале: `<sha1(canonical_key)[:16]><ext>`.

    ОДНА функция на все три раздела зеркала (форум, FAQ, блоги) — до этой
    правки их было две с одинаковым видом имени, но считавшихся от ПОЛНОГО
    URL (`fetch_assets.local_name` и `mirror_faq._local_asset_name`, дефект
    M4 и отложенный пункт 6 итогового ревью Ф2). Из-за хоста и
    percent-encoding в хэше один и тот же файл получал разные имена в
    разных разделах: 90 картинок, вставленных и в FAQ, и в блоги, лежали в
    двух каталогах под двумя именами, а при доборе недостающих 248 картинок
    через `fetch_assets` тот же файл получил бы третье имя.

    Расширение берётся из пути (не из запроса) и только если похоже на
    расширение; иначе `.bin` — у раздачи вложений (`show_file.php?fid=N`)
    расширения в адресе нет вовсе, тип известен только по байтам файла.
    """
    parts = urllib.parse.urlsplit(url or "")
    ext = Path(urllib.parse.unquote(parts.path or "")).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext or ""):
        ext = ".bin"
    return hashlib.sha1(canonical_key(url).encode("utf-8")).hexdigest()[:16] + ext


# Имя, которое даёт `asset_name`, и только оно: по этому виду `write_all`
# отличает файлы, которые положил сам, от чужих файлов в каталоге `assets/`
# (уборка сирот удаляет только свои — см. `mirror.prune_assets`).
ASSET_NAME_RE = re.compile(r"^[0-9a-f]{16}\.[a-z0-9]{1,5}$")
