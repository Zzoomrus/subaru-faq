"""Дедуп FAQ: раздел архивирован двумя движками разом.

Bitrix (`ELEMENT_ID`) и старый самописный движок отдавали один и тот же
раздел, и часть записей попала в базу дважды. Для зеркала это безвредно —
две заметки и две заметки. Для статей смертельно: одна мысль, подкреплённая
двумя сносками, читается как два независимых свидетельства.

Канон — всегда `bitrix`: запись полнее (есть категория и программа) и новее.
Старая запись не удаляется и не правится, ей лишь проставляется указатель
`duplicate_of_*`; удалять данные Ф2 не разрешала, и правильно — приговор
дублю пересматриваем без перекачки.
"""
from __future__ import annotations

import re
import sqlite3

from pipeline import notes

# Порог вхождения ответа: короткий ответ («Да.», «Не стоит.») встречается
# внутри чего угодно и признаком дубля не является. Порог — свойство
# безопасности дедупа, подгонять его под фикстуру теста нельзя (первая
# версия так и сделала — задним числом это признано ошибкой); если фикстура
# короче порога, чинить фикстуру, а не отсиживать порог ниже.
MIN_CONTAINMENT_CHARS = 40

_NON_WORD = re.compile(r"[^0-9a-zа-яё]+")


def normalize_question(text: str) -> str:
    """Правило сравнения вопросов, заданное явно.

    Только буквы и цифры, регистр вниз. Пунктуация, пробелы и вопросительный
    знак игнорируются: движки расставляли их по-разному.
    """
    return _NON_WORD.sub("", (text or "").lower())


def find_duplicates(conn: sqlite3.Connection) -> list[dict]:
    canon = {}
    for nr, question in conn.execute(
        "SELECT nr, question FROM faq WHERE engine = 'bitrix' ORDER BY nr"
    ):
        canon.setdefault(normalize_question(question), nr)

    # Нормализация пробелов ОБЯЗАНА идти здесь, а не на сырой строке из
    # `answer_text`: два движка форума разбивают абзацы по-разному (`\n`
    # у старого движка там, где у Bitrix `\n\n`), и точное посимвольное
    # `in` из-за этого пропускало настоящие дубли (найдено ревью на живых
    # данных — `FAQ старый 114`/`155`). `notes.normalize_spaces` — общая
    # функция с задачей 4 Ф3 (дословная проверка цитат), см. её докстринг:
    # два потребителя одного правила обязаны ходить одной функцией.
    canon_answers = {
        nr: notes.normalize_spaces(answer or "")
        for nr, answer in conn.execute("SELECT nr, answer_text FROM faq WHERE engine = 'bitrix'")
    }

    found: list[dict] = []
    for nr, question, answer in conn.execute(
        "SELECT nr, question, answer_text FROM faq WHERE engine = 'old' ORDER BY nr"
    ):
        key = normalize_question(question)
        if key in canon:
            found.append({
                "engine": "old", "nr": nr,
                "canonical_engine": "bitrix", "canonical_nr": canon[key],
                "reason": "вопрос совпал",
            })
            continue
        body = notes.normalize_spaces(answer or "")
        if len(body) < MIN_CONTAINMENT_CHARS:
            continue
        for canon_nr, canon_body in sorted(canon_answers.items()):
            if body in canon_body:
                found.append({
                    "engine": "old", "nr": nr,
                    "canonical_engine": "bitrix", "canonical_nr": canon_nr,
                    "reason": "ответ дословно внутри канонического",
                })
                break
    return found


def apply(conn: sqlite3.Connection) -> dict:
    """Проставить указатели. Идемпотентно: сначала всё сбрасывается в NULL."""
    conn.execute("UPDATE faq SET duplicate_of_engine = NULL, duplicate_of_nr = NULL")
    dupes = find_duplicates(conn)
    for d in dupes:
        conn.execute(
            "UPDATE faq SET duplicate_of_engine = ?, duplicate_of_nr = ? WHERE engine = ? AND nr = ?",
            (d["canonical_engine"], d["canonical_nr"], d["engine"], d["nr"]),
        )
    conn.commit()
    return {
        "дублей": len(dupes),
        "по вопросу": sum(1 for d in dupes if d["reason"] == "вопрос совпал"),
        "по вхождению ответа": sum(
            1 for d in dupes if d["reason"] == "ответ дословно внутри канонического"
        ),
    }
