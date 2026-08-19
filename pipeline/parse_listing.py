"""Парсер оглавлений разделов форума (list_<FID>_<page>.html).

Строка таблицы описывает одну тему: ссылка на первую страницу темы лежит
внутри ``span.forum-item-title`` (НЕ ``div`` — расхождение с исходным брифом,
проверено на всех 235 файлах оглавлений). Автор темы — единственный
текстовый узел внутри ``span.forum-item-author`` после подписи «автор:» —
там нет отдельного span с именем автора, поэтому имя вырезается регуляркой
из полного текста контейнера, а не селектором на дочерний элемент.

На части страниц (замечено на `list_12_1.html`) исходная разметка таблицы
битая: не хватает закрывающего `</tr>`, из-за чего и `lxml`, и встроенный
`html.parser` кладут десятки последующих строк ВНУТРЬ одного `<tr>` вместо
того, чтобы сделать их соседями. Из-за этого `BeautifulSoup(html).select("tr")`
возвращает не только настоящие строки-темы, но и один такой
контейнер-обёртку, `select_one` внутри которого находит ПЕРВОЕ подходящее
вложенное совпадение — т.е. чужие ячейки `replies`/`views` (не своей темы, а
самой первой в этом слипшемся куске). Наблюдался кейс: TID=15537 (реально
replies=8397/views=2838025) получал из такой строки-контейнера чужие
replies=2669/views=1155788, принадлежащие TID=27731. Число страниц из
`span.forum-item-pages`, как ни странно, там же извлекалось верно — эта
поломка непредсказуема по полям, поэтому такие строки-контейнеры не
чинятся точечно, а целиком отбрасываются: настоящие данные для каждой
темы всё равно присутствуют отдельным, корректно вложенным `<tr>` без
дочерних `<tr>` (см. `_is_leaf_row`).

Число страниц темы вырезается из ``span.forum-item-pages`` конкретной
строки, а не из ``str(row)`` целиком (расхождение с брифом) — так надёжнее
даже для нормальных строк, если рядом окажется другая аномалия разметки.
"""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

_AUTHOR_PREFIX_RE = re.compile(r"^\s*автор\s*:\s*", re.IGNORECASE)
_TID_RE = re.compile(r"TID=(\d+)")
_FID_RE = re.compile(r"FID=(\d+)")
_MID_RE = re.compile(r"MID=(\d+)")
_PAGEN_RE = re.compile(r"PAGEN_1=(\d+)")
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


@dataclass
class ThreadMeta:
    tid: int
    fid: int
    title: str
    author: str
    started_at: str
    replies: int
    views: int
    pages: int
    last_mid: int | None


def _int(node, default: int = 0) -> int:
    if node is None:
        return default
    m = re.search(r"\d+", node.get_text(" ", strip=True))
    return int(m.group()) if m else default


def _iso(ru_date: str) -> str:
    m = _DATE_RE.search(ru_date or "")
    return "%s-%s-%s" % (m.group(3), m.group(2), m.group(1)) if m else ""


def _author(row) -> str:
    node = row.select_one("span.forum-item-author")
    if node is None:
        return ""
    text = node.get_text(" ", strip=True)
    return _AUTHOR_PREFIX_RE.sub("", text).strip()


def _is_leaf_row(row) -> bool:
    """True, если строка не содержит вложенных <tr> — т.е. не является

    контейнером, в который битая разметка таблицы слепила соседние строки.
    """
    return row.find("tr") is None


def parse(html: str) -> list[ThreadMeta]:
    soup = BeautifulSoup(html, "lxml")
    out: list[ThreadMeta] = []
    for row in soup.select("tr"):
        if not _is_leaf_row(row):
            continue
        link = row.select_one('span.forum-item-title a[href*="TID="]')
        if link is None:
            continue
        href = link.get("href", "")
        tid_m = _TID_RE.search(href)
        if tid_m is None:
            continue
        fid_m = _FID_RE.search(href)
        pages_span = row.select_one("span.forum-item-pages")
        pages = {int(m) for m in _PAGEN_RE.findall(str(pages_span))} if pages_span else set()
        pages = pages or {1}
        last = row.select_one("span.forum-lastpost-date a")
        last_mid = None
        if last is not None:
            mid_m = _MID_RE.search(last.get("href", ""))
            last_mid = int(mid_m.group(1)) if mid_m else None
        out.append(ThreadMeta(
            tid=int(tid_m.group(1)),
            fid=int(fid_m.group(1)) if fid_m else 0,
            title=link.get_text(" ", strip=True),
            author=_author(row),
            started_at=_iso(link.get("title", "")),
            replies=_int(row.select_one("td.forum-column-replies span")),
            views=_int(row.select_one("td.forum-column-views span")),
            pages=max(pages),
            last_mid=last_mid,
        ))
    return out
