"""Отчёт покрытия: сколько постов темы сохранилось в архиве против того,
сколько ожидалось по оглавлению форума.

Формула брифа задачи 6 (`COALESCE(replies_expected, 0) + 1`) неверна для
1612 тем, у которых `replies_expected IS NULL` — тема отсутствует во всех
собранных оглавлениях (не сохранилась страница листинга, либо тема
пропала из списка к моменту снятия оглавления Wayback), а строка в
`threads` создана фолбэком `ingest.ensure_thread_from_page` со страницы
темы. Для таких тем "ожидание 1 пост" было бы ложью: сверять не с чем,
а не "сошлось на пустом множестве".

Поэтому темы делятся на пять непересекающихся групп:

- `unverifiable` — `replies_expected IS NULL`, сверка невозможна;
- `missing`      — тема из оглавления, но постов не сохранилось вовсе
                    (`got == 0`);
- `ok`           — тема из оглавления, `got == expected`;
- `short`        — тема из оглавления, `got < expected` (и `got > 0`);
- `extra`        — тема из оглавления, `got > expected`.

Приоритет проверок в `_classify`: сначала `unverifiable` (нет `expected`
— неважно, сколько постов), потом `missing` (`got == 0`), потом знак
`diff`. На реальном корпусе `unverifiable` и `missing` не пересекаются
(фолбэк создаёт строку `threads` только когда у страницы есть хотя бы
один пост), но порядок проверок делает это утверждение инвариантом кода,
а не случайным совпадением данных.
"""
import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import articles, facts, notes, verify


@dataclass
class Row:
    tid: int
    fid: int
    title: str
    expected: int | None
    got: int
    diff: int | None
    group: str


def _classify(expected: int | None, got: int) -> tuple[int | None, str]:
    if expected is None:
        return None, "unverifiable"
    diff = got - expected
    if got == 0:
        return diff, "missing"
    if diff == 0:
        return diff, "ok"
    if diff < 0:
        return diff, "short"
    return diff, "extra"


def report(conn) -> list[Row]:
    sql = """
    SELECT t.tid, t.fid, t.title, t.replies_expected,
           (SELECT COUNT(*) FROM posts p WHERE p.tid = t.tid) AS got
    FROM threads t ORDER BY t.fid, t.tid
    """
    rows = []
    for tid, fid, title, replies_expected, got in conn.execute(sql):
        expected = None if replies_expected is None else replies_expected + 1
        diff, group = _classify(expected, got)
        rows.append(Row(tid, fid, title, expected, got, diff, group))
    return rows


def summary(rows: list[Row]) -> dict[str, int]:
    return {
        "threads": len(rows),
        "ok": sum(1 for r in rows if r.group == "ok"),
        "short": sum(1 for r in rows if r.group == "short"),
        "extra": sum(1 for r in rows if r.group == "extra"),
        "missing": sum(1 for r in rows if r.group == "missing"),
        "unverifiable": sum(1 for r in rows if r.group == "unverifiable"),
    }


def to_csv(rows: list[Row], path: Path) -> None:
    """Пишет отчёт в CSV с BOM: самый вероятный способ его посмотреть —
    открыть в Excel, а Excel на русской Windows без BOM читает UTF-8 как
    кракозябры.
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["tid", "fid", "title", "expected", "got", "diff", "group"])
        for r in rows:
            w.writerow([
                r.tid, r.fid, r.title,
                "" if r.expected is None else r.expected,
                r.got,
                "" if r.diff is None else r.diff,
                r.group,
            ])


# --- Ф3, задача 7: покрытие FAQ/блогов + доля непроцитированных источников -
#
# `report`/`summary` выше считают только форум (решение 36 Ф2, бэклог Ф3
# пункт 2): тема — единственный вид источника с известным "ожидаемым"
# числом постов, а у FAQ/блогов сверить не с чем оглавление. Здесь — не
# сверка ожидания, а простой подсчёт: сколько записей вообще, сколько из
# них можно использовать как дословный источник.
#
# `faq_blog_coverage` делит записи каждого раздела на ЧЕТЫРЕ ГРУППЫ БЕЗ
# ПЕРЕСЕЧЕНИЯ (сумма равна "всего" — инвариант, который проверяет тест):
#
# - `дублей` (только FAQ, `faq.duplicate_of_nr` — задача 1 Ф3): запись
#   реальна, но канон — другая запись; не самостоятельный источник вовсе;
# - `из_одних_картинок` (контракт зеркала §3, 25 FAQ + 8 блогов на живом
#   корпусе): `answer_md`/`body_md` непусты, но `answer_text`/`body_text`
#   пуст — текста нет вовсе, цитировать нечего;
# - `пустых` (только FAQ, контракт §3, 6 записей): `answer_md` пуст
#   целиком — ни текста, ни картинки;
# - `выдержек` (только блоги, контракт §4, `is_excerpt=1`, 56 записей):
#   текст есть, но восстановлен из ленты, не из тела записи — не
#   дословный источник;
# - `с_текстом` — остаток, реальный цитируемый плоский текст.
#
# Приоритет у "дублей": на живом корпусе есть ровно один случай, когда
# запись одновременно дубль И из одних картинок (`FAQ старый 155` —
# см. `docs/ф3-бэклог.md` п.1) — без приоритета она попала бы в ДВЕ
# группы разом, и сумма разошлась бы с "всего" (тот же класс ошибки,
# что уже проверяют "четыре нуля целостности": число, а не факт наличия).
def faq_blog_coverage(conn: sqlite3.Connection) -> dict:
    faq_total, = conn.execute("SELECT COUNT(*) FROM faq").fetchone()
    faq_dup, = conn.execute(
        "SELECT COUNT(*) FROM faq WHERE duplicate_of_nr IS NOT NULL").fetchone()
    faq_image_only, = conn.execute(
        "SELECT COUNT(*) FROM faq WHERE duplicate_of_nr IS NULL AND answer_md <> '' "
        "AND (answer_text IS NULL OR answer_text = '')").fetchone()
    faq_empty, = conn.execute(
        "SELECT COUNT(*) FROM faq WHERE duplicate_of_nr IS NULL "
        "AND (answer_md IS NULL OR answer_md = '')").fetchone()
    faq_with_text, = conn.execute(
        "SELECT COUNT(*) FROM faq WHERE duplicate_of_nr IS NULL "
        "AND answer_text IS NOT NULL AND answer_text <> ''").fetchone()

    blog_total, = conn.execute("SELECT COUNT(*) FROM blog_posts").fetchone()
    blog_excerpt, = conn.execute(
        "SELECT COUNT(*) FROM blog_posts WHERE is_excerpt = 1").fetchone()
    blog_image_only, = conn.execute(
        "SELECT COUNT(*) FROM blog_posts WHERE is_excerpt = 0 AND body_md <> '' "
        "AND (body_text IS NULL OR body_text = '')").fetchone()
    blog_with_text, = conn.execute(
        "SELECT COUNT(*) FROM blog_posts WHERE is_excerpt = 0 "
        "AND body_text IS NOT NULL AND body_text <> ''").fetchone()

    return {
        "faq": {
            "всего": faq_total,
            "дублей": faq_dup,
            "из_одних_картинок": faq_image_only,
            "пустых": faq_empty,
            "с_текстом": faq_with_text,
        },
        "блоги": {
            "всего": blog_total,
            "выдержек": blog_excerpt,
            "из_одних_картинок": blog_image_only,
            "с_текстом": blog_with_text,
        },
    }


# Ревью задачи 7 (находка 1): контракт зеркала §3 запрещает как источник
# 4 класса — пустые темы форума, выдержки блогов, дубли FAQ, записи
# FAQ/блогов из одних картинок, — но у ФОРУМА своего аналога «из одних
# картинок» в контракте не было: тема может иметь ≥1 пост и всё равно не
# нести ни одной цитаты, которая пройдёт `facts.check_one` (посты вида
# «test», «....», «ф», «летние» — контента для факта нет, только шум).
# Живой замер (21.08.2026): **23 темы из 3509** «с постами» — ни один
# пост которых не даёт хотя бы `facts.MIN_QUOTE_CHARS` (8) «чистых» знаков
# после `notes.citable()` (снимает шапки/пометки генератора) и
# `notes.normalize_spaces()` (та же нормализация, что использует гейт
# прохода 1). Раз ни одна цитата такой длины физически не пройдёт гейт —
# тема не источник, структурно то же самое, что «из одних картинок» у
# FAQ/блогов. Решение лида (дообсуждение ревью 22.08.2026): добавить класс,
# исключить из знаменателя, задокументировать в контракте зеркала §3.
#
# Читает `posts.markdown` (не `posts.text`) — тот же канон дословной
# проверки, что и везде в фазе (Global Constraint №1): `facts.check_one`
# сверяет цитату с телом ЗАМЕТКИ, а заметку строит `markdown`, не `text`.
def _mute_forum_threads(conn: sqlite3.Connection) -> set[int]:
    """`tid` тем, где МАКСИМАЛЬНАЯ по длине "чистая" цитата любого поста
    короче `facts.MIN_QUOTE_CHARS` — ни для одной из них не существует
    цитаты, способной пройти гейт прохода 1, независимо от того, что
    напишет ИИ."""
    best_len: dict[int, int] = {}
    for tid, markdown in conn.execute("SELECT tid, markdown FROM posts"):
        clean_len = len(notes.normalize_spaces(notes.citable(markdown or "")).strip())
        if clean_len > best_len.get(tid, -1):
            best_len[tid] = clean_len
    return {tid for tid, length in best_len.items() if length < facts.MIN_QUOTE_CHARS}


def citable_sources(conn: sqlite3.Connection) -> list[str]:
    """Полный список источников корпуса, на которые ВООБЩЕ можно
    сослаться дословной цитатой, — знаменатель `citation_coverage`.

    Дубли FAQ (17 из 174, `faq.duplicate_of_nr`) и выдержки блогов (56 из
    528, `blog_posts.is_excerpt`) исключаются условиями SQL ниже — то же
    самое знание, что несёт `notes.citable_source` (задача 6), просто
    прямым запросом по тем же полям базы, а не вызовом в цикле по каждому
    из ~4800 потенциальных имён: `citable_source` рассчитана на ОДНО
    заданное имя (нужен вызывающему коду одной сноски), здесь нужен список
    всего корпуса разом. **Уточнение по находке 2 ревью задачи 7**:
    пустые темы форума (2829 из 6338) исключает условие `EXISTS posts`
    ниже, а НЕ `notes.citable_source` — та имя вида «Тема N» вообще не
    разбирает (её регэкспы — только `FAQ`/`Блог`) и молча вернула бы
    «цитируемо» для любой пустой темы. Это не расхождение: у пустой темы
    нет ни одного заголовка `##### Пост <MID>`, `notes.section()` вернёт
    `None` раньше, чем вопрос о цитируемости источника вообще возникнет
    (структурная защита через отсутствие якоря в `facts.check_one`, см.
    докстринг `notes.py` про пустые темы) — но МЕХАНИЗМ другой, и раньше
    здесь было написано неверно.

    Записи из одних картинок (33 = 25 FAQ + 8 блогов — `answer_text`/
    `body_text` пуст при непустом `answer_md`/`body_md`) и «немые» темы
    форума (23 из 3509 — см. `_mute_forum_threads`) исключаются отдельными
    условиями: `notes.citable_source` про них не знает вовсе (она про то,
    что ЗАПРЕЩЕНО контрактом, а не про то, есть ли текст физически).
    Включать их в знаменатель было бы нечестно перед мерой «что ИИ молча
    проигнорировал» (`faq_blog_coverage` считает картиночные FAQ/блоги
    отдельной строкой) — они не процитированы не потому, что ИИ проглядел
    источник, а потому что источник немой.
    """
    mute = _mute_forum_threads(conn)
    sources: list[str] = []
    for tid, in conn.execute(
        "SELECT t.tid FROM threads t WHERE EXISTS (SELECT 1 FROM posts p WHERE p.tid = t.tid) "
        "ORDER BY t.tid"):
        if tid not in mute:
            sources.append("Тема %d" % tid)
    for engine, nr in conn.execute(
        "SELECT engine, nr FROM faq WHERE duplicate_of_nr IS NULL "
        "AND answer_text IS NOT NULL AND answer_text <> '' ORDER BY engine, nr"):
        sources.append("FAQ старый %d" % nr if engine == "old" else "FAQ %d" % nr)
    for blog, post_id in conn.execute(
        "SELECT blog, post_id FROM blog_posts WHERE is_excerpt = 0 "
        "AND body_text IS NOT NULL AND body_text <> '' ORDER BY blog, post_id"):
        sources.append("Блог %s %d" % (blog, post_id))
    return sources


def _scan_articles(articles_root: Path) -> tuple[set[str], list[str]]:
    """Множество имён источников (без якоря), процитированных хотя бы
    раз хоть в одной статье дерева `articles_root`, + список файлов
    `*.md`, которые не удалось разобрать вовсе.

    Не заводит свой разбор определения сноски (`[^fN]: «цитата» — ...,
    [[источник]]`) — использует ТУ ЖЕ пару функций, что и проверяльщик
    задачи 6 (`articles._parse_draft`/`_strip_non_prose` +
    `verify._parse_footnote_definitions`): формат сноски один на весь
    проект, вторая копия разбора расходилась бы с первой молча (тот же
    урок Ф2, что и Global Constraint №3 про резолв ссылок, только здесь
    про формат сноски, а не про адрес заметки).

    Находка 4 ревью задачи 7: файл, не прошедший `articles._parse_draft`
    (нет frontmatter вовсе, либо не закрыт), раньше просто пропускался
    (`continue`) — его цитаты (если они там есть) молча выпадали из
    «процитировано», раздувая «не процитировано» ложно, а сам факт, что
    в дереве статей лежит файл, который код не смог прочитать, никуда не
    попадал. Такой путь теперь возвращается вызывающему коду ОТДЕЛЬНО
    (`citation_coverage` кладёт список в `"не_разобрано"`), а не тонет в
    тишине.
    """
    cited: set[str] = set()
    unparsed: list[str] = []
    for path in sorted(Path(articles_root).rglob("*.md")):
        try:
            _, raw_body = articles._parse_draft(path)
        except articles.DraftError:
            unparsed.append(str(path))
            continue
        body = articles._strip_non_prose(raw_body)
        defs, _ = verify._parse_footnote_definitions(body)
        for info in defs.values():
            name = info["источник"].split("#", 1)[0].strip()
            if name:
                cited.add(name)
    return cited, unparsed


def citation_coverage(articles_root: Path, sources: list[str]) -> dict:
    """Доля источников `sources` (обычно — выход `citable_sources`),
    процитированных хотя бы раз хоть в одной статье `articles_root`
    (спека §10: «доля источников пилота, не процитированных ни разу —
    измерена и объяснена»).

    Не о том, что проверяет `verify.check` («источники_без_цитаты» одной
    ГОТОВОЙ статьи — задача 6, спека §6) — а о корпусе целиком: сколько из
    ВСЕХ источников, на которые вообще можно сослаться, статьи хоть где-то
    процитировали. Источник, упомянутый в двух сносках одной статьи или в
    сносках двух разных статей, считается процитированным ОДИН раз — он
    один и тот же источник, а не два по числу сносок.

    `доля` — доля НЕ процитированных (та величина, которую называет спека
    §10), а не процитированных: 0 при пустом `sources` (нечего делить, а
    не деление на ноль).

    `"не_разобрано"` (находка 4 ревью задачи 7) — файлы `*.md` дерева
    `articles_root`, которые не удалось разобрать вовсе (нет/не закрыт
    frontmatter): их цитаты не попадают ни в «процитировано», ни в явном
    виде в «не процитировано» — не потому что источники не процитированы,
    а потому что статья, которая могла бы их процитировать, не прочиталась.
    Смешивать это с честным «источник не процитирован» значило бы молча
    завышать охват непроцитированного, поэтому список — отдельно.
    """
    cited_in_articles, unparsed = _scan_articles(articles_root)
    # `dict.fromkeys` — де-дуп с сохранением порядка: `sources` может
    # прийти с повторами (конкатенация нескольких запросов), а источник —
    # не два, если назван дважды.
    unique_sources = list(dict.fromkeys(sources))
    uncited = sorted(s for s in unique_sources if s not in cited_in_articles)
    n_cited = sum(1 for s in unique_sources if s in cited_in_articles)
    total = len(unique_sources)
    return {
        "процитировано": n_cited,
        "не процитировано": len(uncited),
        "доля": (len(uncited) / total) if total else 0.0,
        "список": uncited,
        "не_разобрано": sorted(unparsed),
    }
