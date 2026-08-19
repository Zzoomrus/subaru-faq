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
