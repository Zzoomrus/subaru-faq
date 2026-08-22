"""Проверка целостности вики: битые межзаметочные ссылки, битые вставки
файлов, битые якоря и задвоенные якоря внутри одной заметки.

Проверяется всё дерево вики, а не один плоский каталог: спека кладёт
источники в `Источники/`, а статьи следующей фазы — в `Статьи/Тормоза/`,
`Статьи/Модели/GC8/`. Ключ заметки — путь относительно корня вики без
расширения, поэтому одноимённые заметки в разных папках не схлопываются
(дефект I6: плоский `glob("*.md")` с ключом по имени файла давал либо
«все ссылки на источники битые», либо «статьи не проверены вовсе»).

Ссылка ищется в двух видах якоря:

- заголовочный `[[Тема 42335#Пост 391784]]` — основной вид после переделки
  зеркала (генератор ставит заголовок `##### Пост <MID>`). Раньше такая
  ссылка регуляркой не матчилась вовсе: `#` был исключён из класса символов
  цели, альтернативы не было, и ссылка молча не проверялась — отсутствие
  находок было неотличимо от отсутствия проверки;
- блочный `[[Тема 42335#^p391784]]` — генератор их больше не ставит, но
  статьи могут ссылаться и так, и проверка обязана их понимать.

Разрешение цели повторяет поведение Obsidian: сначала точный относительный
путь, потом имя заметки (Obsidian резолвит вики-ссылку по имени файла).
Если имя неоднозначно (две заметки с одним именем в разных папках),
якорь сверяется с объединением их якорей — это заведомое приближение:
неоднозначность имени в вики надо не диагностировать здесь, а не
допускать.

Фронтматтер при поиске ссылок пропускается: `[[` экранируется генератором
только в теле поста, а в названии темы или имени автора — нет (отложенная
находка №9; сегодня таких строк в базе 0, но фронтматтер статей следующей
фазы станет богаче). Режется он по ЗАКРЫВАЮЩЕЙ СТРОКЕ `---`, а не по
первому вхождению подстроки: у четырёх тем корпуса `---` стоит внутри
названия (Ruling 25).

Заметки читаются как обычный текст и разбираются регулярками — без
парсинга Markdown/Obsidian-синтаксиса целиком.

Вставка файла `![[путь]]` (генератор зеркала вставляет так картинки, задача
4 фазы Ф2) отличается от ссылки на заметку `[[путь]]` ровно восклицательным
знаком перед скобками — но этого признака мало, чтобы понять, ЧТО
проверять: цель ссылки ищется среди ЗАМЕТОК (`notes`/`by_name`), а цель
вставки — среди ФАЙЛОВ вики (`files`/`by_file_name`), это два разных
пространства имён, и `assets/host/abc.jpg` никогда не найдётся среди
заметок, даже если файл на месте. Поэтому:

- `LINK` получил негативный lookbehind `(?<!!)` — `![[...]]` для него
  больше не совпадение вовсе, вставки полностью выпадают из проверки ссылок
  на заметки (иначе ЛЮБАЯ вставка после задачи 4 репортилась бы как битая
  ссылка на несуществующую «заметку по имени файла» — сотни/тысячи ложных
  находок, как только фаза добора положит первый файл).
- Отдельный `EMBED` ищет `![[...]]` и резолвится по индексу файлов дерева
  (`directory.rglob("*")`, а не только `*.md`) — тем же приёмом «точный
  путь, потом по имени файла», что и для заметок (см. `_resolve`), только
  без проверки якоря: у вставки картинки якоря не бывает, а вставка секции
  чужой заметки (`![[Заметка#Заголовок]]`) генератором не производится —
  если она когда-нибудь понадобится, довод для отдельного якорного разбора
  появится вместе с ней, а не раньше.
"""
import re
from collections import Counter
from pathlib import Path

# `[[цель#якорь|подпись]]`: цель и подпись необязательны (`[[#Заголовок]]` —
# ссылка внутри той же заметки). `(?<!!)` исключает вставки `![[...]]` —
# у них своё пространство целей (файлы, не заметки), см. docstring модуля.
LINK = re.compile(r"(?<!!)\[\[([^\[\]|#]*)(#[^\[\]|]+)?(?:\|[^\[\]]*)?\]\]")
# `![[путь]]` / `![[путь|подпись]]` — вставка файла. Цель — группа 1;
# необязательный якорь/подпись после неё не проверяются (см. docstring).
EMBED = re.compile(r"!\[\[([^\[\]|#]*)(?:#[^\[\]|]+)?(?:\|[^\[\]]*)?\]\]")
# Блочный идентификатор в конце строки. Obsidian допускает в нём латиницу,
# цифры и дефис.
BLOCK_ANCHOR = re.compile(r"\^([A-Za-z0-9-]+)\s*$", re.M)
# ATX-заголовок. Хвостовые решётки (`## Заголовок ##`) в имя якоря не входят.
HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)


def _strip_frontmatter(text: str) -> str:
    """Отрезает YAML-фронтматтер по закрывающей строке `---`."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join(lines[i + 1:])
    # Незакрытый фронтматтер — считаем, что его нет: лучше проверить лишнее,
    # чем молча не проверить всю заметку.
    return text


def build_notes_index(directory: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Индекс заметок поддерева вики: `notes` (ключ без расширения -> текст) и
    `by_name` (имя файла без пути -> список ключей с таким именем в разных
    папках). Тот же индекс, которым `check()` резолвит цель ссылки — второй
    потребитель (`pipeline.facts`, задача 4 Ф3) обязан брать его отсюда, а
    не строить свой обход `rglob`: Global Constraint №3 фазы («ссылки
    резолвит check_mirror, своей цепочки резолва не писать») существует
    ровно на случай второго потребителя одного знания — иначе он разойдётся
    с этим молча, как разошлись `sync_to_db`/`local_path` в Ф2.
    """
    directory = Path(directory)
    notes: dict[str, str] = {}
    for path in sorted(directory.rglob("*.md")):
        key = path.relative_to(directory).with_suffix("").as_posix()
        notes[key] = path.read_text(encoding="utf-8")

    by_name: dict[str, list[str]] = {}
    for key in notes:
        by_name.setdefault(key.rsplit("/", 1)[-1], []).append(key)
    return notes, by_name


def resolve_note(target: str, notes: dict[str, str], by_name: dict[str, list[str]]) -> list[str] | None:
    """Резолвит ИМЯ заметки (без якоря, `target` — то, что стоит до `#` в
    `[[Цель#Якорь]]`) в список ключей — Obsidian сначала ищет точный
    относительный путь, потом по имени файла. Несколько заметок с
    одинаковым именем в разных папках — все совпадения разом, вызывающий
    код сам решает, что делать с неоднозначностью (`check()` сверяет якорь
    с ОБЪЕДИНЕНИЕМ их якорей, `pipeline.facts` — отказывает факту явной
    причиной).

    Пустая цель (`[[#Заголовок]]`, ссылка внутри той же заметки) сюда не
    относится — это забота вызывающего кода (`check()._resolve` подставляет
    исходную заметку сама, до вызова этой функции).
    """
    target = target.strip()
    if target.endswith(".md"):
        target = target[:-3]
    if target in notes:
        return [target]
    return by_name.get(target.rsplit("/", 1)[-1])


def build_heading_index(notes: dict[str, str]) -> dict[str, list[str]]:
    """Заголовки каждой заметки индекса `notes` (`build_notes_index`) — та
    же операция, что раньше жила инлайном внутри `check()`. Выделена, чтобы
    якорную проверку (`anchor_exists` ниже) мог переиспользовать второй
    потребитель (`pipeline.verify`, задача 6 Ф3) — до этой правки якорь
    ссылки в ПРОЗЕ статьи не сверялся вовсе, хотя ровно этот код уже умеет
    (находка Н4 ревью задачи 6: `check_mirror.check` сверяет, а `verify.py`
    выбрасывал якорь из ссылки, довольствуясь тем, что цель существует)."""
    return {key: HEADING.findall(text) for key, text in notes.items()}


def build_block_index(notes: dict[str, str]) -> dict[str, list[str]]:
    """Блочные идентификаторы (`^abc123`) каждой заметки — см.
    `build_heading_index` выше, тот же приём и та же причина выделения."""
    return {key: BLOCK_ANCHOR.findall(text) for key, text in notes.items()}


def anchor_exists(resolved_keys: list[str], anchor: str,
                   headings: dict[str, list[str]], blocks: dict[str, list[str]]) -> bool:
    """Есть ли `anchor` (уже БЕЗ ведущей `#`) хотя бы у одной из заметок
    `resolved_keys` — при неоднозначном имени (`resolve_note` вернул
    несколько ключей) якорь сверяется с ОБЪЕДИНЕНИЕМ, как и раньше в
    `check()`. Блочный якорь (`^abc123`) и путь по подзаголовкам
    (`#Раздел#Подраздел`) — те же два вида, что понимал инлайн-код `check()`
    до выделения; поведение НЕ изменилось, тесты `test_check_mirror.py` и
    `test_anchor_contract.py` держат это ровно так же, как до рефакторинга.
    """
    if anchor.startswith("^"):
        return any(anchor[1:] in blocks.get(r, []) for r in resolved_keys)
    segments = [s.strip() for s in anchor.split("#") if s.strip()]
    return any(all(s in headings.get(r, []) for s in segments) for r in resolved_keys)


def check(directory: Path) -> dict[str, list[str]]:
    directory = Path(directory)
    notes, by_name = build_notes_index(directory)

    # Индекс ФАЙЛОВ (не только заметок) — цель вставки `![[путь]]` резолвится
    # среди них, а не среди заметок (см. docstring модуля). Ключ — путь с
    # расширением, в отличие от `notes` (там расширение снято).
    files: set[str] = set()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            files.add(path.relative_to(directory).as_posix())

    by_file_name: dict[str, list[str]] = {}
    for key in files:
        by_file_name.setdefault(key.rsplit("/", 1)[-1], []).append(key)

    headings = build_heading_index(notes)
    blocks = build_block_index(notes)

    dupes = []
    for key in notes:
        for anchor, count in Counter(blocks[key]).items():
            if count > 1:
                dupes.append("%s: ^%s встречается %d раз" % (key, anchor, count))
        for heading, count in Counter(headings[key]).items():
            if count > 1:
                dupes.append("%s: заголовок «%s» встречается %d раз" % (key, heading, count))

    def _resolve(target: str, source: str) -> list[str] | None:
        target = target.strip()
        if not target:
            return [source]
        return resolve_note(target, notes, by_name) or None

    def _file_exists(target: str) -> bool:
        target = target.strip()
        if not target:
            return False
        if target in files:
            return True
        return bool(by_file_name.get(target.rsplit("/", 1)[-1]))

    broken_links, broken_anchors, broken_embeds = [], [], []
    for key, text in notes.items():
        body = _strip_frontmatter(text)
        for target in EMBED.findall(body):
            if not _file_exists(target):
                broken_embeds.append("%s -> ![[%s]]" % (key, target.strip()))
        for target, anchor in LINK.findall(body):
            resolved = _resolve(target, key)
            if resolved is None:
                broken_links.append("%s -> [[%s]]" % (key, target.strip()))
                continue
            if not anchor:
                continue
            anchor = anchor[1:]  # снимаем ведущую `#`
            ok = anchor_exists(resolved, anchor, headings, blocks)
            if not ok:
                broken_anchors.append("%s -> [[%s#%s]]" % (key, target.strip(), anchor))

    return {"broken_links": sorted(broken_links),
            "broken_anchors": sorted(broken_anchors),
            "duplicate_anchors": sorted(dupes),
            "broken_embeds": sorted(broken_embeds)}
