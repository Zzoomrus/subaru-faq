"""Проверка целостности зеркала: битые межзаметочные ссылки, битые якоря
блочных ссылок и задвоенные якоря внутри одной заметки.

Формат ссылок и якорей зафиксирован генератором (`pipeline.mirror`):
имя заметки — `Тема <TID>` (без расширения при вики-ссылке), якорь —
`^p<MID>` в конце строки. Здесь заметки читаются как обычный текст и
разбираются регулярками — без парсинга Markdown/Obsidian-синтаксиса
целиком, ровно как в брифе задачи.

На текущем корпусе (задача 8, фаза Ф0+Ф1) заметки зеркала друг на друга
вообще не ссылаются — межзаметочные ссылки появятся только в следующей
фазе, когда над зеркалом вырастут статьи. Поэтому `broken_links` и
`broken_anchors` на реальном прогоне закономерно равны нулю: это не
признак того, что проверка работает, а признак того, что ей пока нечего
ловить. Способность ловить обе категории проверена синтетическими
тестами (`tests/test_check_mirror.py`), не полагающимися на реальные
данные.
"""
import re
from collections import Counter
from pathlib import Path

LINK = re.compile(r"\[\[([^\]|#]+)(?:#\^(p\d+))?(?:\|[^\]]*)?\]\]")
ANCHOR = re.compile(r"\^(p\d+)\s*$", re.M)


def check(directory: Path) -> dict[str, list[str]]:
    directory = Path(directory)
    notes = {p.stem: p.read_text(encoding="utf-8") for p in directory.glob("*.md")}
    anchors = {name: set(ANCHOR.findall(text)) for name, text in notes.items()}

    dupes = []
    for name, text in notes.items():
        for anchor, count in Counter(ANCHOR.findall(text)).items():
            if count > 1:
                dupes.append("%s: ^%s встречается %d раз" % (name, anchor, count))

    broken_links, broken_anchors = [], []
    for name, text in notes.items():
        for target, anchor in LINK.findall(text):
            target = target.strip()
            if target not in notes:
                broken_links.append("%s -> [[%s]]" % (name, target))
                continue
            if anchor and anchor not in anchors[target]:
                broken_anchors.append("%s -> [[%s#^%s]]" % (name, target, anchor))

    return {"broken_links": sorted(broken_links),
            "broken_anchors": sorted(broken_anchors),
            "duplicate_anchors": sorted(dupes)}
