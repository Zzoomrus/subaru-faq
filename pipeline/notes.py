"""Единственный способ прочитать то, на что указывает сноска.

Канон дословной проверки Ф2 (решение 30) — ТЕЛО ЗАМЕТКИ, не поле базы:
`posts.text` и `posts.markdown` расходятся у 27267 постов из 48689. Заметки
воспроизводятся байт-в-байт и физически являются целью сноски, значит они и
есть истина.

Секция кончается заголовком ЛЮБОГО уровня: в заметке темы посты размечены
`##### Пост <MID>`, но внутри поста может встретиться строка, начинающаяся
с `#` (в Ф1 таких нашлось 22-26, они экранированы генератором). Правило
«до следующего заголовка любого уровня» совпадает с тем, как секцию
понимает Obsidian, — а сноска адресует именно его.
"""
from __future__ import annotations

import re
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)

#: Строки, которые написал генератор зеркала, а не человек. Цитировать их
#: нельзя: проверка дословности прошла бы, подтвердив несуществующие слова.
GENERATOR_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\(изображение не сохранилось:[^)]*\)"),
    re.compile(r"^\(пустой комментарий\)$", re.M),
    re.compile(r"^\(пусто\)$", re.M),
    # Шапка поста: «*Автор · 28.02.2015 18:35:30 · #1*»
    re.compile(r"^\*[^*\n]+ · \d{2}\.\d{2}\.\d{4}[^*\n]*\*$", re.M),
    # Вставка картинки — адрес файла, а не слова автора.
    re.compile(r"!\[\[[^\]]+\]\]"),
)


def body(path: Path) -> str:
    text = Path(path).read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    return text


def section(path: Path, anchor: str) -> str | None:
    text = body(path)
    matches = list(HEADING.finditer(text))
    for i, m in enumerate(matches):
        if m.group(2).strip() == anchor.strip():
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            return text[start:end].strip("\n")
    return None


def citable(text: str) -> str:
    for pattern in GENERATOR_PATTERNS:
        text = pattern.sub(" ", text)
    return text
