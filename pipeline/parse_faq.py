"""Парсер страниц раздела FAQ (Ф2, задача 6).

Раздел архивирован ДВУМЯ движками разом (см. отчёт задачи 5, "Главная
находка"): современным Bitrix (`/faq/index.php?ELEMENT_ID=N`, разметка
ответа — `div.catalog-element`) и старым самописным (`/faq/faq.php?
display=faq&nr=N&catnr=C&prog=P`, разметка — `td.question`/`td.answer`:
метка "Вопрос:"/"Ответ:", затем СЛЕДОМ вторая ячейка того же класса с
текстом). На живом корпусе (177 файлов) — 154 Bitrix и 23 старых, разбор
проверен на всех, не только на фикстурах (см. task-6-report.md).

Важная находка разведки задачи 6: `nr` (старый движок) и `ELEMENT_ID`
(Bitrix) — НЕЗАВИСИМЫЕ пространства номеров, которые реально пересекаются
(17 из 177 файлов несут одно и то же число под разным содержанием —
подтверждено сверкой текста вопроса). Поэтому `FaqEntry` не полагается на
`nr` как на глобально уникальный ключ — уникальность даёт пара
`(engine, nr)`, и `pipeline.mirror_faq` использует её же для имени файла.

Курьёз того же корпуса: старый движок иногда показывает ОДНУ И ТУ ЖЕ
запись под двумя разными (nr, catnr) — cross-листинг в двух категориях
(проверено: nr=106 catnr=25/prog=COMMON и nr=106 catnr=26/prog=DRIVE несут
дословно одинаковые вопрос и ответ, хидден-поле `nr` формы совпадает).
Значит `nr` ВНУТРИ старого движка — корректный ключ дедупа сам по себе;
`load_all` схлопывает по нему, оставляя первую по порядку обхода файлов
категорию (см. её docstring).
"""
import logging
import re
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from pipeline import assets_state, db, fetch_site, html_text

_LOG = logging.getLogger(__name__)

# Базовые адреса для относительных ссылок (`../upload/blog/...`) ответа.
# Оба скрипта раздела всегда лежат ровно по этому пути — конкретные query-
# параметры (ELEMENT_ID/nr/...) на результат urljoin с ОТНОСИТЕЛЬНЫМ путём
# не влияют, поэтому не нужно протаскивать реальный URL страницы через
# сигнатуру `parse(html)` (она — буквально по брифу, один аргумент).
_BASE_BITRIX = "http://www.subaru-faq.ru/faq/index.php"
_BASE_OLD = "http://www.subaru-faq.ru/faq/faq.php"

_BACK_LINK_TEXT = "Назад в раздел"

# `![]()` целиком, как рендерит `html_text.to_markdown` (URL может содержать
# один уровень вложенных скобок — та же осторожность, что в `html_text`/
# `mirror._IMG_MD`, см. их докстринги).
_IMG_MD = re.compile(r"!\[\]\(((?:[^()]|\([^()]*\))*)\)")


def _absolutize_images(markdown: str, base: str) -> str:
    """Переписывает `![](относительный/url)` на абсолютный, СРАЗУ после
    рендера в markdown — иначе `entry.images` (нужен абсолютный адрес для
    сверки с уже скачанными вложениями Ф0/Ф1, см. `pipeline.mirror_faq`) и
    сам текст ответа несли бы РАЗНЫЕ формы одного и того же URL: находка
    задачи 6 — `mirror.render_post_body` ищет картинку в тексте по URL
    буквально, и малейшее расхождение (relative vs absolute) превращает
    каждую найденную картинку в "потерянную" в тексте и в "сироту" в конце
    заметки одновременно (оба неверных сразу, тот же URL под двумя видами).
    """
    return _IMG_MD.sub(lambda m: "![](%s)" % urllib.parse.urljoin(base, m.group(1)), markdown)


@dataclass
class FaqEntry:
    nr: int
    engine: str  # "bitrix" | "old"
    catnr: int | None
    prog: str
    category: str
    question: str
    answer_md: str
    images: list[str] = field(default_factory=list)
    # Заголовок темы (h1), когда он расходится с настоящим вопросом,
    # найденным ВНУТРИ тела ответа (см. `_split_embedded_qa`) — `None` у
    # старого движка (там `question` и так из `td.question`) и у Bitrix,
    # когда дублирования вообще нет или заголовок совпадает с вопросом.
    title: str | None = None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# Дефект задачи 6 (найден лидом на живом корпусе, пример FAQ 103): часть
# страниц Bitrix (70 из 154 — см. task-6-report.md) несёт в теле
# `catalog-element` СВОЙ дублирующий "Вопрос:"/"Ответ:" — тело мигрировало
# со старого движка целиком, вместе с метками, вместо того чтобы остаться
# просто ответом. Устроено ТРЕМЯ разными способами (проверено на всех 70):
#   - метка "Ответ:" одна, без вопроса (34) — заголовок h1 уже несёт
#     настоящий вопрос, нужно только убрать служебное слово;
#   - метка "Вопрос:" с текстом ВОПРОСА, затем метка "Ответ:" (34) — и вот
#     тут заголовок h1 сплошь и рядом (32 из 34) несёт не сам вопрос, а
#     название темы ("Рекомендации по использованию прицепов...") —
#     настоящий вопрос лежит только в теле;
#   - метка "Вопрос:" вовсе без "Ответ:" (2, FAQ 120 и FAQ 223) — не
#     обрамлена ничем, поэтому НЕ пытаемся угадать, где вопрос кончается и
#     начинается ответ (см. предостережение в докстринге `_split_embedded_
#     qa`), просто убираем самую метку.
# Все три видны исключительно у Bitrix (проверено на всех 23 файлах старого
# движка — ни одного случая): у старого движка `question` и так берётся из
# отдельной ячейки `td.question`, дублировать ей неоткуда.
_ANSWER_LABEL_ONLY = re.compile(r"^\s*Ответ\s*:\s*", re.S)
# Гэп после "Вопрос:" — ЖАДНЫЙ `\s*` (в отличие от предыдущей ревизии этого
# regex): здесь это безопасно, потому что регекс ограничен СПРАВА
# однозначным якорем "Ответ:", а не первой попавшейся пустой строкой —
# сколько бы пустых строк (стиль <br><br> у части страниц, пример FAQ 141)
# ни было внутри самого вопроса, `.*?` остановится ровно на "Ответ:".
_QUESTION_WITH_ANSWER_LABEL = re.compile(r"^\s*Вопрос\s*:?\s*(?P<q>.*?)\s*\n\s*Ответ\s*:\s*", re.S)
# Без парного "Ответ:" граница вопроса неоднозначна — на живом корпусе она
# ОБА раза приходится на пустую строку сразу после метки, но означает
# противоположное: у FAQ 120 сразу за меткой идёт настоящий вопрос (просто
# через один перевод строки, не через пустую строку — тут пустой строки как
# раз НЕТ), у FAQ 223 — пустая строка и следом список ссылок без единого
# слова вопроса. Различить эти два случая надёжно нечем (оба текстовые, без
# доп. разметки), поэтому вместо угадывания — только снять саму метку и
# оставить текст как есть: не идеально для FAQ 120 (вопрос останется
# нетронутым текстом внутри ответа), но безопасно для FAQ 223 (не
# придумываем вопрос из списка ссылок, см. task-6-report.md).
_QUESTION_LABEL_BARE = re.compile(r"^\s*Вопрос\s*:?\s*", re.S)


def _split_embedded_qa(answer_md: str) -> tuple[str | None, str]:
    """Срезает служебные метки "Вопрос:"/"Ответ:" из тела ответа Bitrix.

    Возвращает `(вопрос_из_тела | None, очищенный_ответ)`. `None` для
    вопроса значит: либо дублирования не было вовсе, либо была только
    метка "Ответ:" без вопроса (заголовок h1 уже верен), либо "Вопрос:"
    стояла без парной "Ответ:" (граница вопроса неоднозначна — см. докстринг
    `_QUESTION_LABEL_BARE`, снимается только метка).
    """
    m = _QUESTION_WITH_ANSWER_LABEL.match(answer_md)
    if m:
        return (_clean(m.group("q")) or None), answer_md[m.end():].lstrip("\n ")
    m = _ANSWER_LABEL_ONLY.match(answer_md)
    if m:
        return None, answer_md[m.end():].lstrip("\n ")
    m = _QUESTION_LABEL_BARE.match(answer_md)
    if m:
        return None, answer_md[m.end():].lstrip("\n ")
    return None, answer_md


def _loosely_equal(a: str, b: str) -> bool:
    """Сравнение вопроса из тела с заголовком h1 без шума пунктуации/
    регистра — на живом корпусе 2 из 34 страниц с embedded-вопросом несут
    его словно в словно (буква в букву, кроме этого шума).
    """
    norm = lambda s: re.sub(r"[\s.?!:;,\"'«»]+", " ", s.strip().lower()).strip()
    return norm(a) == norm(b)


def _bitrix_id(html: str) -> int | None:
    """Номер записи — самое частое число из ВСЕХ вхождений `ELEMENT_ID=N`
    на странице (ссылка "печать" в шапке, форма логина, backurl, ...).

    На полном корпусе (154 файла) все вхождения на одной странице совпадают
    без единого исключения — "самое частое" здесь эквивалентно "любое", но
    устойчивее к гипотетическому будущему снимку, где случайно затесалось
    чужое число (см. task-6-report.md, сверка адреса с номером внутри
    страницы). У 2 файлов из 154 нет верхнего меню (урезанный ajax-снимок
    `bitrix_include_areas`) — ссылки "печать" нет, но хидден-поле `backurl`
    формы логина несёт тот же номер и переживает даже такой снимок.
    """
    ids = re.findall(r"ELEMENT_ID=(\d+)", html)
    if not ids:
        return None
    return Counter(int(i) for i in ids).most_common(1)[0][0]


def _parse_bitrix(soup: BeautifulSoup, html: str) -> FaqEntry | None:
    ce = soup.select_one("div.catalog-element")
    if ce is None:
        return None
    nr = _bitrix_id(html)
    if nr is None:
        return None

    h1 = soup.select_one("h1#pagetitle")
    question = _clean(h1.get_text(" ", strip=True)) if h1 else ""

    # Хлебные крошки: "Главная > FAQ > <раздел> > <категория...>" — первые
    # два пункта общие для всего раздела, за ними — от 1 до 3 уровней
    # категории (проверено на всех 154: длина 3/4/5 пунктов). `prog` — первый
    # уровень категории (аналог кода "программы" старого движка, но текстом:
    # Bitrix такого кода не несёт вовсе); `category` — полный хвост.
    crumbs = [_clean(a.get_text(" ", strip=True))
              for a in soup.select("ul.breadcrumb-navigation li a")]
    tail = crumbs[2:]
    prog = tail[0] if tail else ""
    category = " › ".join(tail)

    # Разметка catalog-element (проверено на всех 154 файлах, см.
    # task-6-report.md): первая дочерняя `<table>` — пустая вёрстка-обёртка
    # (0 непустых из 154), последняя ссылка — "Назад в раздел" (152 из 154;
    # у 2 файлов ссылок в блоке нет вовсе — тогда резать нечего). Срезаем
    # ОБА хвоста ДО рендера в markdown, а не постфактум по тексту: иначе
    # "Назад в раздел" рисковал бы совпасть с настоящим текстом ответа.
    first_table = ce.find("table", recursive=False)
    if first_table is not None and not first_table.get_text(strip=True):
        first_table.extract()
    links = ce.find_all("a")
    if links and _clean(links[-1].get_text(" ", strip=True)) == _BACK_LINK_TEXT:
        links[-1].extract()

    inner = ce.decode_contents()
    answer_md = _absolutize_images(html_text.to_markdown(inner), _BASE_BITRIX)
    images = [urllib.parse.urljoin(_BASE_BITRIX, u) for u in html_text.images(inner)]

    # Снять дублирующие метки/вопрос из тела (см. docstring
    # `_split_embedded_qa`) ДО экранирования заголовков/wikilink в
    # `mirror_faq.render_entry` — иначе "Вопрос:"/"Ответ:" остались бы в
    # заметке рядом с настоящим ответом.
    embedded_question, answer_md = _split_embedded_qa(answer_md)
    title = None
    if embedded_question and not _loosely_equal(embedded_question, question):
        # Заголовок h1 — название темы, а не вопрос (см. пример FAQ 103 в
        # докстринге модуля): настоящий вопрос важнее, заголовок уходит в
        # `title` — `mirror_faq` кладёт его в aliases, а не теряет.
        title = question
        question = embedded_question

    return FaqEntry(nr=nr, engine="bitrix", catnr=None, prog=prog, category=category,
                     question=question, answer_md=answer_md, images=images, title=title)


def _parse_old(soup: BeautifulSoup) -> FaqEntry | None:
    qs = soup.select("td.question")
    ans = soup.select("td.answer")
    if len(qs) < 2 or len(ans) < 2:
        return None

    # Разметка без единого контейнера записи (см. брифа задачи 6): первая
    # ячейка каждого класса — метка "Вопрос:"/"Ответ:", вторая — текст.
    question = _clean(qs[1].get_text(" ", strip=True))
    answer_inner = ans[1].decode_contents()
    answer_md = _absolutize_images(html_text.to_markdown(answer_inner), _BASE_OLD)
    images = [urllib.parse.urljoin(_BASE_OLD, u) for u in html_text.images(answer_inner)]

    # nr/catnr/prog — из хидден-полей формы оценки (`rateform`), не из URL:
    # `parse(html)` намеренно не принимает URL, а хидден-поля несут те же
    # значения (сверено на всех 23 файлах корпуса — 0 расхождений с URL).
    hidden = {inp.get("name"): inp.get("value")
              for inp in soup.select("input[type=hidden]")}
    nr = hidden.get("nr")
    if nr is None or not str(nr).isdigit():
        return None
    catnr = hidden.get("catnr")
    prog = hidden.get("prog") or ""

    # Заголовок раздела вида "SUBARU - в общем. : Общая информация ... : Тема
    # группы." — три сегмента, разделённых " : " (проверено на всех 23: ровно
    # 3 сегмента без исключений). Второй сегмент — человекочитаемое имя
    # категории, соответствующее `catnr`; первый — имя `prog`. Третий сегмент
    # — заголовок ГРУППЫ вопросов, а не текст самого вопроса (тот — в
    # `td.question`), поэтому в `category` не идёт.
    sh = soup.select_one("td.subheading span")
    segs = [s.strip() for s in _clean(sh.get_text(" ", strip=True)).split(":")] if sh else []
    category = " › ".join(s for s in segs[:2] if s)

    return FaqEntry(nr=int(nr), engine="old", catnr=int(catnr) if catnr and catnr.isdigit() else None,
                     prog=prog, category=category, question=question, answer_md=answer_md, images=images)


def parse(html: str) -> FaqEntry | None:
    """Разбирает ОДНУ страницу FAQ, в любом из двух движков сайта.

    `None` — страница не несёт отдельного вопроса-ответа (категория/листинг
    старого движка, служебная/сбойная страница) или его не удалось надёжно
    привязать к номеру.
    """
    soup = BeautifulSoup(html, "lxml")
    if soup.select_one("div.catalog-element") is not None:
        return _parse_bitrix(soup, html)
    if soup.select_one("td.question") is not None and soup.select_one("td.answer") is not None:
        return _parse_old(soup)
    return None


def _plan_ts_by_url(site_root: Path) -> dict[str, str]:
    """Метка снимка (`ts`) по URL — из уже посчитанного плана задачи 5.

    Манифест добора (`manifest-site.jsonl`) саму метку не хранит (только
    url/path/status/note) — план остаётся единственным источником. Метка в
    плане — то, что `fetch_all` пробовал СКАЧАТЬ первым; если этот снимок
    оказался пустышкой, реально мог сохраниться другой (см. `fetch_site.
    fetch_all`) — значение приближённое, помечено так же в отчёте задачи 6.
    """
    try:
        plan = fetch_site.load_plan("faq", root=site_root)
    except FileNotFoundError:
        return {}
    return {item["url"]: item.get("ts", "") for item in plan}


def load_all(site_root: Path, site_manifest: Path, conn) -> dict[str, int]:
    """Разбирает все успешно скачанные страницы FAQ и пишет их в таблицу `faq`.

    Источник состояния — манифест добора (см. `fetch_site.fetch_all`):
    только записи со `status == "ok"` в разделе `/faq/` реально скачаны на
    диск, остальные (`empty`/`failed`/не встречавшиеся) пропускаются молча
    — это ожидаемо (см. task-6-report.md о расхождении ~194 -> 177), а не
    повод падать.

    Обход файлов идёт в ОТСОРТИРОВАННОМ по URL порядке — детерминизм важен
    для дедупа: на живом корпусе один и тот же `(engine, nr)` может дать
    больше одной страницы (см. docstring модуля — истинный дубль-URL
    nr=48 и cross-листинг nr=106/107), и без стабильного порядка обхода
    победитель менялся бы от прогона к прогону. Побеждает ПОСЛЕДНЯЯ по
    сортировке страница (`INSERT OR REPLACE`) — при истинном дубле-URL
    содержимое идентично и порядок не важен по факту, при cross-листинге
    результат детерминирован и то же самое было бы верно для "первой".
    """
    stats = {"pages": 0, "parsed": 0, "empty_question": 0, "empty_answer": 0,
              "skipped_not_ok": 0, "unparsed": 0, "duplicates": 0, "images": 0}
    known = assets_state.load(site_manifest)
    ts_by_url = _plan_ts_by_url(site_root)
    seen_keys: set[tuple] = set()

    faq_urls = sorted(url for url, rec in known.items()
                       if "/faq/" in url and rec.get("status") == "ok" and rec.get("path"))
    for url in faq_urls:
        rec = known[url]
        stats["pages"] += 1
        path = Path(site_root) / rec["path"]
        html = path.read_bytes().decode("cp1251", "replace")
        entry = parse(html)
        if entry is None:
            stats["unparsed"] += 1
            _LOG.warning("faq: не удалось разобрать %s (%s)", url, rec["path"])
            continue
        if not entry.question:
            stats["empty_question"] += 1
        if not entry.answer_md:
            stats["empty_answer"] += 1

        key = (entry.engine, entry.nr)
        if key in seen_keys:
            stats["duplicates"] += 1
        seen_keys.add(key)

        # `answer_text` — плоский текст ответа для поиска (`faq_fts`), тот же
        # смысл и та же функция, что у `posts.text` (дефект I1 итогового
        # ревью Ф2). Считается ЗДЕСЬ, а не в `parse`: разбор страницы отдаёт
        # markdown, плоский текст — производная от него, и разбирать HTML
        # второй раз незачем (тот же довод, что в докстринге
        # `html_text.plain_text_from_markdown`).
        answer_text = html_text.plain_text_from_markdown(entry.answer_md or "")
        conn.execute(
            "INSERT INTO faq(engine, nr, catnr, prog, category, question, answer_md, source_url, "
            "snapshot_ts, title, answer_text) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(engine, nr) DO UPDATE SET "
            "catnr=excluded.catnr, prog=excluded.prog, category=excluded.category, "
            "question=excluded.question, answer_md=excluded.answer_md, "
            "source_url=excluded.source_url, snapshot_ts=excluded.snapshot_ts, title=excluded.title, "
            "answer_text=excluded.answer_text",
            (entry.engine, entry.nr, entry.catnr, entry.prog, entry.category,
             entry.question, entry.answer_md, url, ts_by_url.get(url, ""), entry.title,
             answer_text))
        # Картинки этой записи — полностью пересчитываем при каждой загрузке
        # (см. `upsert_post`/`ingest_all` для прецедента "чужого" паттерна;
        # здесь он не нужен — записей мало, полный пересчёт дешевле, чем
        # аккуратный дифф).
        conn.execute("DELETE FROM faq_images WHERE engine = ? AND nr = ?", (entry.engine, entry.nr))
        for img_url in entry.images:
            conn.execute("INSERT INTO faq_images(engine, nr, url, local_path) VALUES (?,?,?,NULL)",
                         (entry.engine, entry.nr, img_url))
            stats["images"] += 1
        stats["parsed"] += 1

    conn.commit()
    stats.update(db.rebuild_search_index(conn))
    return stats
