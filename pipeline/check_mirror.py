"""Проверка целостности вики: битые межзаметочные ссылки, битые якоря и
задвоенные якоря внутри одной заметки.

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
"""
import re
from collections import Counter
from pathlib import Path

# `[[цель#якорь|подпись]]`: цель и подпись необязательны (`[[#Заголовок]]` —
# ссылка внутри той же заметки).
LINK = re.compile(r"\[\[([^\[\]|#]*)(#[^\[\]|]+)?(?:\|[^\[\]]*)?\]\]")
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


def check(directory: Path) -> dict[str, list[str]]:
    directory = Path(directory)
    notes: dict[str, str] = {}
    for path in sorted(directory.rglob("*.md")):
        key = path.relative_to(directory).with_suffix("").as_posix()
        notes[key] = path.read_text(encoding="utf-8")

    by_name: dict[str, list[str]] = {}
    for key in notes:
        by_name.setdefault(key.rsplit("/", 1)[-1], []).append(key)

    headings = {key: HEADING.findall(text) for key, text in notes.items()}
    blocks = {key: BLOCK_ANCHOR.findall(text) for key, text in notes.items()}

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
        if target.endswith(".md"):
            target = target[:-3]
        if target in notes:
            return [target]
        hits = by_name.get(target.rsplit("/", 1)[-1])
        return hits or None

    broken_links, broken_anchors = [], []
    for key, text in notes.items():
        body = _strip_frontmatter(text)
        for target, anchor in LINK.findall(body):
            resolved = _resolve(target, key)
            if resolved is None:
                broken_links.append("%s -> [[%s]]" % (key, target.strip()))
                continue
            if not anchor:
                continue
            anchor = anchor[1:]  # снимаем ведущую `#`
            if anchor.startswith("^"):
                ok = any(anchor[1:] in blocks[r] for r in resolved)
            else:
                # Путь по подзаголовкам `#Раздел#Подраздел`: приближение —
                # требуем, чтобы каждый сегмент был заголовком целевой
                # заметки (вложенность не проверяется).
                segments = [s.strip() for s in anchor.split("#") if s.strip()]
                ok = any(all(s in headings[r] for s in segments) for r in resolved)
            if not ok:
                broken_anchors.append("%s -> [[%s#%s]]" % (key, target.strip(), anchor))

    return {"broken_links": sorted(broken_links),
            "broken_anchors": sorted(broken_anchors),
            "duplicate_anchors": sorted(dupes)}
