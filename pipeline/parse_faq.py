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

from pipeline import assets_state, fetch_site, html_text

_LOG = logging.getLogger(__name__)

# Базовые адреса для относительных ссылок (`../upload/blog/...`) ответа.
# Оба скрипта раздела всегда лежат ровно по этому пути — конкретные query-
# параметры (ELEMENT_ID/nr/...) на результат urljoin с ОТНОСИТЕЛЬНЫМ путём
# не влияют, поэтому не нужно протаскивать реальный URL страницы через
# сигнатуру `parse(html)` (она — буквально по брифу, один аргумент).
_BASE_BITRIX = "http://www.subaru-faq.ru/faq/index.php"
_BASE_OLD = "http://www.subaru-faq.ru/faq/faq.php"

_BACK_LINK_TEXT = "Назад в раздел"


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


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


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
    answer_md = html_text.to_markdown(inner)
    images = [urllib.parse.urljoin(_BASE_BITRIX, u) for u in html_text.images(inner)]

    return FaqEntry(nr=nr, engine="bitrix", catnr=None, prog=prog, category=category,
                     question=question, answer_md=answer_md, images=images)


def _parse_old(soup: BeautifulSoup) -> FaqEntry | None:
    qs = soup.select("td.question")
    ans = soup.select("td.answer")
    if len(qs) < 2 or len(ans) < 2:
        return None

    # Разметка без единого контейнера записи (см. брифа задачи 6): первая
    # ячейка каждого класса — метка "Вопрос:"/"Ответ:", вторая — текст.
    question = _clean(qs[1].get_text(" ", strip=True))
    answer_inner = ans[1].decode_contents()
    answer_md = html_text.to_markdown(answer_inner)
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

        conn.execute(
            "INSERT INTO faq(engine, nr, catnr, prog, category, question, answer_md, source_url, snapshot_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(engine, nr) DO UPDATE SET "
            "catnr=excluded.catnr, prog=excluded.prog, category=excluded.category, "
            "question=excluded.question, answer_md=excluded.answer_md, "
            "source_url=excluded.source_url, snapshot_ts=excluded.snapshot_ts",
            (entry.engine, entry.nr, entry.catnr, entry.prog, entry.category,
             entry.question, entry.answer_md, url, ts_by_url.get(url, "")))
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
    return stats
