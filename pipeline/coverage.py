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

from . import articles, verify


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


def citable_sources(conn: sqlite3.Connection) -> list[str]:
    """Полный список источников корпуса, на которые ВООБЩЕ можно
    сослаться дословной цитатой, — знаменатель `citation_coverage`.

    Три класса контракта (`docs/контракт-зеркала.md` §3-4), которые сюда
    не попадают, — те же три, что различает `notes.citable_source`
    (задача 6): пустые темы форума (2829 из 6338), выдержки блогов (56
    из 528), дубли FAQ (17 из 174). Не переизобретается заново — но
    `notes.citable_source` проверяет ОДНО заданное имя (нужен вызывающему
    коду сноски), а здесь нужен список ВСЕГО корпуса сразу, и дешевле
    получить его прямыми запросами по тем же полям базы, чем звать
    `citable_source` в цикле по каждому имени.

    ЧЕТВЁРТЫЙ класс, которого `notes.citable_source` не касается вовсе
    (он про то, что ЗАПРЕЩЕНО контрактом, а не про то, есть ли текст) —
    33 записи из одних картинок (25 FAQ + 8 блогов): цитировать формально
    не запрещено, но физически нечего — `answer_text`/`body_text` пуст.
    Включать их в знаменатель было бы нечестно перед мерой «что ИИ
    молча проигнорировал» (см. `faq_blog_coverage` — считает их отдельной
    строкой) — они не процитированы не потому, что ИИ проглядел источник,
    а потому что источник немой.
    """
    sources: list[str] = []
    for tid, in conn.execute(
        "SELECT t.tid FROM threads t WHERE EXISTS (SELECT 1 FROM posts p WHERE p.tid = t.tid) "
        "ORDER BY t.tid"):
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


def _cited_sources(articles_root: Path) -> set[str]:
    """Множество имён источников (без якоря), процитированных хотя бы
    раз хоть в одной статье дерева `articles_root`.

    Не заводит свой разбор определения сноски (`[^fN]: «цитата» — ...,
    [[источник]]`) — использует ТУ ЖЕ пару функций, что и проверяльщик
    задачи 6 (`articles._parse_draft`/`_strip_non_prose` +
    `verify._parse_footnote_definitions`): формат сноски один на весь
    проект, вторая копия разбора расходилась бы с первой молча (тот же
    урок Ф2, что и Global Constraint №3 про резолв ссылок, только здесь
    про формат сноски, а не про адрес заметки).
    """
    cited: set[str] = set()
    for path in sorted(Path(articles_root).rglob("*.md")):
        try:
            _, raw_body = articles._parse_draft(path)
        except articles.DraftError:
            continue
        body = articles._strip_non_prose(raw_body)
        defs, _ = verify._parse_footnote_definitions(body)
        for info in defs.values():
            name = info["источник"].split("#", 1)[0].strip()
            if name:
                cited.add(name)
    return cited


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
    """
    cited_in_articles = _cited_sources(articles_root)
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
    }
