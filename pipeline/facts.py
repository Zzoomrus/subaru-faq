"""Проход 1: приём и механическая проверка фактов, выданных ИИ.

Ценность фазы не в том, что ИИ пишет связный текст, а в том, что соврать
ему нечем: факт, чья цитата не найдена дословно в теле заметки, до прозы не
доживает. Поэтому проверка здесь — не валидация формата, а гейт.

Сверяется ТЕЛО ЗАМЕТКИ (канон дословной проверки, `docs/контракт-зеркала.md`
§2), причём очищенное от текста генератора (`notes.citable`): в зеркале
6341 пометка «(изображение не сохранилось: …)», и цитата из неё прошла бы
проверку, подтвердив несуществующие слова автора.

Имя заметки резолвится через `check_mirror.build_notes_index`/`resolve_note`
— ту же цепочку, которой Obsidian и `check_mirror.check` разрешают
`[[Тема 1#Пост 100]]`. Global Constraint фазы №3 запрещает писать здесь свою:
два потребителя одного знания, разошедшиеся молча, — урок Ф2 (`local_path`).
"""
from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from . import check_mirror, notes


def normalize(text: str) -> str:
    """Схлопнуть пробелы: перенос строки в заметке не является подделкой.

    Делегирует `notes.normalize_spaces`, а не заводит свою копию регэкспа —
    у схлопывания пробелов уже есть один потребитель (`pipeline.faq_dedup`,
    задача 1 Ф3) и урок ревью той задачи: два экземпляра одного правила
    разошлись молча (два движка форума бьют абзацы по-разному), и дедуп
    пропустил настоящие дубли, пока сравнение шло сырой строкой. Здесь та
    же природа расхождения — см. докстринг `notes.normalize_spaces`.
    """
    return notes.normalize_spaces(text)


@lru_cache(maxsize=None)
def _notes_index(mirror_root: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    # Кэш по строке корня: в пределах одного прогона `facts check-all` над
    # одной и той же вики дерево не меняется, а фактов — десятки на статью.
    # Без кэша каждый факт заново читал бы текст ВСЕХ заметок корпуса.
    return check_mirror.build_notes_index(Path(mirror_root))


def _resolve_note(mirror_root: Path, name: str) -> tuple[Path | None, str]:
    """Резолвит ИМЯ заметки (без якоря) в файл через `check_mirror` — не
    свою цепочку (Global Constraint №3).

    Возвращает `(путь, причина)`: путь `None`, если заметка не найдена ИЛИ
    имя неоднозначно (несколько заметок с одинаковым именем в разных
    папках — угадывать здесь нельзя, `check_mirror.check` в этом случае
    сверяет объединение их якорей, но для цитаты подстановка чужой заметки
    недопустима), причина — только когда путь `None`.
    """
    notes_index, by_name = _notes_index(str(Path(mirror_root)))
    hits = check_mirror.resolve_note(name, notes_index, by_name)
    if not hits:
        return None, "заметка «%s» не найдена" % name
    if len(hits) > 1:
        return None, "имя «%s» неоднозначно: %s" % (name, ", ".join(sorted(hits)))
    return Path(mirror_root) / (hits[0] + ".md"), ""


def check_one(fact: dict, mirror_root: Path) -> tuple[bool, str]:
    source = (fact.get("источник") or "").strip()
    quote = (fact.get("цитата") or "").strip()
    if not source or not quote:
        return False, "у факта нет источника или цитаты"

    name, _, anchor = source.partition("#")
    name = name.strip()
    anchor = anchor.strip()
    path, reason = _resolve_note(mirror_root, name)
    if path is None:
        return False, reason

    text = notes.section(path, anchor) if anchor else notes.body(path)
    if text is None:
        return False, "якорь «%s» в заметке «%s» отсутствует" % (anchor, name)

    raw = normalize(text)
    clean = normalize(notes.citable(text))
    needle = normalize(quote)

    if needle in clean:
        return True, ""
    if needle in raw:
        return False, "цитата попадает в текст генератора, а не автора"
    return False, "цитата не найдена дословно в источнике"


def check_all(facts: list[dict], mirror_root: Path, conn: sqlite3.Connection | None = None) -> dict:
    passed, dropped = [], []
    for fact in facts:
        ok, reason = check_one(fact, mirror_root)
        if ok:
            item = dict(fact)
            item["id"] = "f%d" % (len(passed) + 1)
            passed.append(item)
        else:
            dropped.append({"факт": fact, "причина": reason})
    return {
        "проверено": passed,
        "отброшено": dropped,
        "статистика": {"всего": len(facts), "прошло": len(passed), "отброшено": len(dropped)},
    }
