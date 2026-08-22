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

import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from . import check_mirror, notes

# Разбор `источника` факта на имя заметки и, если есть, номер поста/
# комментария из якоря — только это нужно, чтобы достать автора/дату из
# базы (`_lookup_meta` ниже). Виды сносок — закрытый список
# (`docs/контракт-зеркала.md` §1), эти три формы имени заметки и два вида
# якоря его исчерпывают.
_NOTE_THEME = re.compile(r"^Тема (\d+)$")
_NOTE_FAQ = re.compile(r"^FAQ (старый )?(\d+)$")
_NOTE_BLOG = re.compile(r"^Блог (\S+) (\d+)$")
_ANCHOR_POST = re.compile(r"^Пост (\d+)$")
_ANCHOR_COMMENT = re.compile(r"^Комментарий (\d+)$")


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
    """Прогоняет `facts` через `check_one`; прошедшим присваивает `id`
    (`f1`, `f2`, … по порядку прохождения) и, если дан `conn`, дописывает
    `автор`/`дату` из базы (`_lookup_meta`) — ИЗ БАЗЫ, а не из ответа ИИ:
    иначе ИИ мог бы подписать чужую цитату правдоподобным, но не своим
    именем (следующая задача рендерит этими полями сноску, см. докстринг
    `_lookup_meta`). `conn` необязателен (программные вызовы/тесты без базы
    под рукой) — тогда ключи `автор`/`дата` у прошедших фактов попросту не
    добавляются, а не становятся `None` незапрошенно.
    """
    passed, dropped = [], []
    for fact in facts:
        ok, reason = check_one(fact, mirror_root)
        if ok:
            item = dict(fact)
            item["id"] = "f%d" % (len(passed) + 1)
            if conn is not None:
                author, date = _lookup_meta(item.get("источник", ""), conn)
                item["автор"] = author
                item["дата"] = date
            passed.append(item)
        else:
            dropped.append({"факт": fact, "причина": reason})
    return {
        "проверено": passed,
        "отброшено": dropped,
        "статистика": {"всего": len(facts), "прошло": len(passed), "отброшено": len(dropped)},
    }


# --- автор/дата из базы -----------------------------------------------------

# ISO-дата в начале строки: `posts.posted_at` («2014-10-11 12:00:00»),
# `threads.started_at` («2014-10-11»).
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
# Дата уже в русском виде в начале строки: `blog_posts.posted_at`/
# `blog_comments.posted_at` («11.10.2014 12:00:00») — у блогов её так
# отформатировал парсер (задача 7 Ф2), в отличие от форума.
_RU_DATE = re.compile(r"^(\d{2}\.\d{2}\.\d{4})")


def _only_date(value: str | None) -> str | None:
    """Дата без времени, в формате footnote-спеки (`docs/контракт-зеркала.md`
    §1, «Razum, 11.10.2014») — НЕ то же преобразование, что `mirror._ru_dt`:
    та собирает дату-и-время для шапки поста в заметке («11.10.2014
    12:00:00»), эта — только дату для сноски и умеет оба сырых формата,
    которые реально лежат в трёх таблицах (форум/темы — ISO, блоги — уже
    русский с временем), а не один.
    """
    if not value:
        return None
    m = _ISO_DATE.match(value)
    if m:
        y, mo, d = m.groups()
        return "%s.%s.%s" % (d, mo, y)
    m = _RU_DATE.match(value)
    if m:
        return m.group(1)
    return value


def _lookup_meta(source: str, conn: sqlite3.Connection) -> tuple[str | None, str | None]:
    """Автор и дата факта — ИЗ БАЗЫ по номеру поста/комментария из якоря,
    не из ответа ИИ.

    Три раздела зеркала несут это по-разному:
    - форум: `posts.author`/`posted_at` по `mid` из якоря `#Пост <MID>`;
      без якоря (сноска на тему целиком) — автор и дата ПЕРВОГО сообщения
      темы из `threads.author`/`started_at` (заполнено у 4726 тем из 6338 —
      падение на `(None, None)` у остальных ожидаемо, не ошибка);
    - блог: `blog_posts.author`/`posted_at` (запись/сноска без якоря) или
      `blog_comments.author`/`posted_at` по `#Комментарий <N>` — комментарий
      несёт СВОИ автора и дату, отдельные от записи;
    - FAQ: настоящего автора и даты НЕТ — вопрос/ответ базы знаний, а не
      реплика форумчанина. У записи есть только `snapshot_ts` — момент,
      когда её СНЯЛ краулер, а не когда написали; подставить его в «дату»
      сноски значило бы приписать записи чужую (архивную) дату как будто
      авторскую — обман того же рода, для защиты от которого затеян
      проект. Поэтому FAQ всегда даёт `(None, None)`.
    """
    name, _, anchor = source.partition("#")
    name = name.strip()
    anchor = anchor.strip()

    m = _NOTE_THEME.match(name)
    if m:
        tid = int(m.group(1))
        pm = _ANCHOR_POST.match(anchor)
        if pm:
            row = conn.execute("SELECT author, posted_at FROM posts WHERE mid = ?",
                                (int(pm.group(1)),)).fetchone()
        else:
            row = conn.execute("SELECT author, started_at FROM threads WHERE tid = ?", (tid,)).fetchone()
        if not row:
            return None, None
        return row[0], _only_date(row[1])

    if _NOTE_FAQ.match(name):
        return None, None

    m = _NOTE_BLOG.match(name)
    if m:
        blog, post_id = m.group(1), int(m.group(2))
        cm = _ANCHOR_COMMENT.match(anchor)
        if cm:
            row = conn.execute(
                "SELECT author, posted_at FROM blog_comments "
                "WHERE blog = ? AND post_id = ? AND comment_id = ?",
                (blog, post_id, int(cm.group(1)))).fetchone()
        else:
            row = conn.execute("SELECT author, posted_at FROM blog_posts WHERE blog = ? AND post_id = ?",
                                (blog, post_id)).fetchone()
        if not row:
            return None, None
        return row[0], _only_date(row[1])

    return None, None
