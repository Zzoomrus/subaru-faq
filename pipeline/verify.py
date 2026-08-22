"""Последний рубеж фазы Ф3 (задача 6): проверяльщик готовой статьи.

Спека §8 называет его главным тестом проекта: проверяльщику, который не
ловит подделку, верить нельзя, поэтому его самого проверяют враньём
(`tests/test_verify.py`, `tests/подделки/`). Работает на уже СОБРАННОЙ
статье (`pipeline.articles.render`/`build`), а не на черновике — предыдущие
рубежи (гейт фактов `pipeline.facts`, запрет встроенной сноски
`pipeline.articles`) защищают процесс сборки; этот модуль исходит из того,
что процесс мог быть обойдён (статья подменена вручную, собрана старой
версией кода, испорчена при переносе) и сверяет РЕЗУЛЬТАТ заново, с нуля.

Своих цепочек резолва не заводит (Global Constraint фазы №3): ссылка на
заметку резолвится `check_mirror.build_notes_index`/`resolve_note`, а
дословность цитаты и цитируемость источника — `pipeline.facts.check_one`
(та же функция, что использует гейт прохода 1, включая
`notes.citable_source` — дубли FAQ и выдержки блогов). Это единственное
намеренное дублирование логики с `pipeline.articles`: подпись сноски
(автор/дата) сверяется НЕЗАВИСИМО, тем же строителем строки
(`articles._footnote_line`), но с автором/датой, взятыми заново из базы —
если бы этот модуль доверял подписи, уже стоящей в статье, вторая линия
обороны ничего не проверяла бы поверх первой.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import articles, check_mirror, facts

# --- определения сносок в ГОТОВОЙ статье -------------------------------------
#
# Форма ЗАДАНА `articles._footnote_line` — не переизобретается: «маркер,
# двоеточие, «цитата» — [подпись,] [[источник]]». Подпись (автор, дата)
# необязательна (запись FAQ); источник — ВСЕГДА последняя вики-ссылка в
# строке. `.+` для цитаты жадный — если в самой цитате когда-нибудь
# встретится «» — [[», это по-прежнему разберётся верно (жадность берёт
# ПОСЛЕДНЕЕ вхождение разделителя в строке).
_FOOTNOTE_DEF = re.compile(r"^\[\^(?P<id>[^\]\s]+)\]:\s+«(?P<quote>.+)»\s+—\s+(?P<rest>.+)$", re.M)
_SOURCE_IN_REST = re.compile(r"\[\[([^\]]+)\]\]\s*$")


def _parse_footnote_definitions(body: str) -> tuple[dict[str, dict], list[str]]:
    """Определения сносок готовой статьи -> `{id: {"цитата", "источник",
    "строка"}}` + список проблем формата (ссылки нет вовсе, id повторён).

    Не привязано к разделу «## Сноски» — сканирует ВЕСЬ текст: подделка
    вправе разместить поддельное определение где угодно, а не только в
    ожидаемом месте.
    """
    defs: dict[str, dict] = {}
    problems: list[str] = []
    for m in _FOOTNOTE_DEF.finditer(body):
        fid = m.group("id")
        rest = m.group("rest")
        src_m = _SOURCE_IN_REST.search(rest)
        if not src_m:
            problems.append("определение сноски [^%s] не содержит ссылки [[...]] на источник" % fid)
            continue
        if fid in defs:
            problems.append("определение сноски [^%s] встречается более одного раза" % fid)
            continue
        defs[fid] = {"цитата": m.group("quote"), "источник": src_m.group(1).strip(), "строка": m.group(0)}
    return defs, problems


# --- числа с единицами измерения ---------------------------------------------
#
# Правила нормализации — бриф задачи 6, дословно: запятая/точка
# равнозначны, внутренние пробелы числа игнорируются, единица приклеена или
# отделена ОДНИМ пробелом, латиница/кириллица единицы равнозначны, диапазон
# `10-12 мм` — два числа, дробь `3/16` — строка целиком, число БЕЗ единицы
# (номер поста, год, артикул) не проверяется вовсе.
#
# Список единиц — ЗАКРЫТЫЙ и сознательно консервативный: любое слово после
# числа не годится в единицы (иначе «1992 год» стало бы «числом с единицей
# „год“» и потребовало бы дословного «1992 год» в сноске — ложная
# находка на честной статье, год цитировать не нужно по брифу).
_UNITS_RAW = (
    "мм", "см", "км", "кг", "мл", "атм", "бар", "нм", "градус", "градуса", "градусов",
    "дюйм", "дюйма", "дюймов",
    "mm", "cm", "km", "kg", "ml", "atm", "bar", "nm", "psi", "rpm", "hp", "cc",
)
_UNIT_ALT = "|".join(sorted({re.escape(u) for u in _UNITS_RAW}, key=len, reverse=True))
_NUM = r"\d[\d\s]*(?:[.,]\d+)?"
_FRACTION = r"\d+\s*/\s*\d+"
_RANGE = re.compile(r"(?P<n1>%s)\s*-\s*(?P<n2>%s)\s*(?P<unit>%s)\b" % (_NUM, _NUM, _UNIT_ALT), re.IGNORECASE)
_SINGLE = re.compile(r"(?P<num>%s|%s)\s?(?P<unit>%s)\b" % (_FRACTION, _NUM, _UNIT_ALT), re.IGNORECASE)

# Транслитерация кириллица -> латиница для сравнения единицы вне
# зависимости от алфавита («mm» == «мм», «kg» == «кг» — бриф задачи 6).
# Стандартная научная транслитерация одной буквы в одну — не визуальное
# сходство (у визуального «р»~«p» смысл был бы другим — «бар» стал бы
# «баp», а не «bar»).
_CYR_TO_LAT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch",
    "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


def _canon_unit(unit: str) -> str:
    return unit.strip().lower().translate(_CYR_TO_LAT)


def _canon_number(raw: str) -> str:
    raw = raw.strip()
    if "/" in raw:
        return raw.replace(" ", "")
    return raw.replace(" ", "").replace(",", ".")


def find_number_units(text: str) -> set[tuple[str, str]]:
    """Числа с единицами измерения в `text`, канонизированные для сравнения.

    Симметричная функция — применяется и к предложению прозы, и к цитате
    сноски ОДНИМ и тем же кодом, а не двумя копиями одного правила: иначе
    они разойдутся молча (тот же урок Ф2, что и у `notes.normalize_spaces`).
    Диапазон `10-12 мм` даёт ДВЕ пары — `("10","mm")` и `("12","mm")`,
    каждая обязана найтись отдельно (бриф задачи 6).
    """
    found: set[tuple[str, str]] = set()
    spans: list[tuple[int, int]] = []
    for m in _RANGE.finditer(text):
        spans.append((m.start(), m.end()))
        unit = _canon_unit(m.group("unit"))
        found.add((_canon_number(m.group("n1")), unit))
        found.add((_canon_number(m.group("n2")), unit))

    def _inside_range(pos: int) -> bool:
        return any(a <= pos < b for a, b in spans)

    for m in _SINGLE.finditer(text):
        if _inside_range(m.start()):
            continue
        found.add((_canon_number(m.group("num")), _canon_unit(m.group("unit"))))
    return found


_PARA_SPLIT = re.compile(r"\n\s*\n")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    """Предложения прозы — абзац за абзацем, заголовки и коллауты-строки
    генератора (`>`, `#`) исключены: это не слова ИИ о фактах, а разметка."""
    out: list[str] = []
    for para in _PARA_SPLIT.split(text):
        para = para.strip()
        if not para or para.startswith("#") or para.startswith(">"):
            continue
        out.extend(s.strip() for s in _SENT_SPLIT.split(para) if s.strip())
    return out


def check(article_path: Path, mirror_root: Path, conn: sqlite3.Connection) -> dict:
    """Проверяет готовую статью `article_path` против зеркала `mirror_root`
    и базы `conn`. Возвращает `{"ок": bool, "проблемы": [...],
    "источники_без_цитаты": [...]}`.

    `источники_без_цитаты` — из frontmatter `неиспользованные_факты`
    (спека §6 — доля фактов, которые ИИ молча проигнорировал): это МЕРА, не
    нарушение контракта (пропущенный, но честный факт — не ложь), поэтому
    не входит в `проблемы` и не сбивает `ок`.
    """
    article_path = Path(article_path)
    mirror_root = Path(mirror_root)

    try:
        meta, body = articles._parse_draft(article_path)
    except articles.DraftError as e:
        return {"ок": False, "проблемы": [str(e)], "источники_без_цитаты": []}

    problems: list[str] = []

    defs, def_problems = _parse_footnote_definitions(body)
    problems += def_problems

    # 1. Каждый маркер обязан иметь определение сноски, и наоборот —
    # определения ищутся отдельно от маркеров (`_FOOTNOTE_DEF.sub` вырезает
    # СТРОКИ определений целиком), иначе `[^f1]:` засчитал бы сам себя как
    # использование `[^f1]` в прозе, и проверка не могла бы поймать ничего.
    prose = _FOOTNOTE_DEF.sub("", body)
    used = set(articles.used_ids(prose))
    defined = set(defs)
    for fid in sorted(used - defined):
        problems.append("маркер [^%s] в тексте не имеет определения сноски" % fid)
    for fid in sorted(defined - used):
        problems.append("определение сноски [^%s] не используется ни одним маркером текста" % fid)

    # 2. Ссылка резолвится через check_mirror (готовый резолв, не своя
    # цепочка — Global Constraint фазы №3). Сканирует ВЕСЬ текст, а не
    # только источники сносок: прозе ничто не мешает содержать ещё и
    # самостоятельные вики-ссылки («смотри также»), которые `facts.check_one`
    # ниже никогда не увидит (он получает только источники ИЗ определений).
    notes_index, by_name = check_mirror.build_notes_index(mirror_root)
    for target, _anchor in check_mirror.LINK.findall(body):
        target = target.strip()
        if target and not check_mirror.resolve_note(target, notes_index, by_name):
            problems.append("ссылка [[%s]] не резолвится ни в одну заметку зеркала" % target)

    # 2-бис. Имя статьи (= её файл, `articles.build` пишет `<заголовок>.md`)
    # НЕ совпадает с именем ни одной заметки-источника. `check_mirror.check`
    # никогда не увидит эту дыру: при полной сборке вики (`Источники/` и
    # `Статьи/` в ОДНОМ дереве, как их проверяет `run check`) статья и
    # источник с одинаковым базовым именем в разных папках становятся ДВУМЯ
    # заметками с одним и тем же именем, а резолв по имени (`resolve_note`,
    # как и сам Obsidian) в такой ситуации не различает их — либо считает
    # обе цели ОДНОВРЕМЕННО валидными (объединяя якоря, поведение
    # `check_mirror.check`), либо, как реально делает сам Obsidian, тихо
    # открывает ПЕРВУЮ найденную. В обоих случаях сноска молча резолвится (в
    # том числе) в САМУ СТАТЬЮ вместо архивного источника — а `mirror_root`
    # здесь содержит только `Источники/`, без самой статьи, так что ни этот
    # проход, ни `facts.check_one` выше такую двусмысленность увидеть не
    # могут: она возникает только когда статья реально ляжет в общее дерево.
    if article_path.stem in by_name:
        problems.append(
            "имя статьи «%s» совпадает с именем заметки-источника в зеркале — при сборке "
            "статьи и источников в одно дерево ссылка на этот источник станет неоднозначной "
            "и может молча резолвиться в саму статью" % article_path.stem)

    # 3-4. Дословность цитаты, цитируемость источника (дубль FAQ/выдержка
    # блога — `notes.citable_source` изнутри `check_one`) и «цитата не из
    # генератора» — всё это уже умеет `facts.check_one`, вызывать заново не
    # нужно (Global Constraint №3 плюс явное указание брифа: дословность
    # берём у `facts.check_one`, своей не пишем).
    #
    # Подпись (автор/дата) сверяется НЕЗАВИСИМО и только для тех сносок,
    # что прошли `check_one`: если цитата уже подделана, о подписи сообщать
    # избыточно и запутывает причину отказа.
    for fid, info in sorted(defs.items()):
        ok, reason = facts.check_one({"источник": info["источник"], "цитата": info["цитата"]},
                                      mirror_root, conn)
        if not ok:
            problems.append("сноска [^%s]: %s" % (fid, reason))
            continue

        author, when = facts._lookup_meta(info["источник"], conn)
        expected = articles._footnote_line({
            "id": fid, "источник": info["источник"], "цитата": info["цитата"],
            "автор": author, "дата": when,
        })
        if expected != info["строка"]:
            problems.append(
                "сноска [^%s]: подпись и/или ссылка не совпадают с тем, что база знает про "
                "источник (ожидалось «%s», в статье «%s»)" % (fid, expected, info["строка"]))

    # 5. Каждое число с единицей измерения в предложении обязано найтись
    # хотя бы в одной сноске ЭТОГО предложения — подмену цифр (самое
    # опасное для техбазы) не ловит ничего из проверок выше: и дословная
    # цитата, и подпись могут быть настоящими у СОСЕДНЕГО факта, который
    # просто оказался в одном предложении с искажённым числом.
    for sentence in _sentences(prose):
        occurrences = find_number_units(sentence)
        if not occurrences:
            continue
        covered: set[tuple[str, str]] = set()
        for fid in articles.used_ids(sentence):
            if fid in defs:
                covered |= find_number_units(defs[fid]["цитата"])
        for num, unit in sorted(occurrences - covered):
            problems.append(
                "число «%s %s» в предложении «%s» не встречается ни в одной сноске этого "
                "предложения" % (num, unit, sentence))

    return {
        "ок": not problems,
        "проблемы": problems,
        "источники_без_цитаты": meta.get("неиспользованные_факты", []),
    }
