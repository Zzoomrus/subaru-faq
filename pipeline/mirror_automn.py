"""Генератор зеркала «Руководство»: заметка на каждую страницу живого
руководства automn.ru (Subaru Legacy/Outback и Forester), скачанного
`tools/fetch_automn.py` в `data/automn/`.

Третий источник вики, и он устроен ИНАЧЕ, чем форум/FAQ/блоги: те три
проходят через `ingest` в SQLite, этот — читает HTML прямо с диска по
манифесту добора (`url -> status/file`, тот же вид, что пишет
`fetch_automn.py`). Своей таблицы в базе намеренно нет: здесь нет ни
дедупа между источниками, ни перекрёстных запросов между записями — одна
HTML-страница даёт ровно одну заметку, без пересечений, значит и повод
заводить SQL-таблицу отсутствует.

Разведка перед правкой (не бриф, а прямой просмотр 805 скачанных страниц)
разошлась с ожиданием: бриф называл `div.left-content` контейнером текста,
но на живых страницах `left-content` — это МЕНЮ (поиск, разделы каталога),
а тело лежит в `#contentblock > div.content`, и делится там на две ветки:

- `div.article-content-text` — 751 из 805, страницы процедур/спецификаций
  (заголовок в `content-header h1` вида `11.13 Название`, есть таблицы —
  692 страницы, картинки — 661);
- `div.content-text` — 54 из 805, вводные страницы категорий (заголовок
  без номера главы, картинок 50, таблиц ни одной).

Заголовок (`h1`) несёт номер главы как читаемый префикс (`11.13`,
`6.2.5`, `14.37.10` — до двух вложенных уровней), кроме двух страниц
обложки тома (`Автомобили Subaru ... г. в.`), у них номера нет. Заголовок
без номера, без манула — коллизия имени: 46 групп из 805, буквально
одинаковый текст заголовка встречается в ОБОИХ томах (Legacy/Outback и
Forester ведут параллельную нумерацию глав) — ни разу ВНУТРИ одного тома
(проверено прямым замером). Имя заметки поэтому — `Руководство <том>
<заголовок>.md`, тот же приём, что и `Блог <слаг> <ID>` (`mirror_blog`):
устраняет коллизию между томами, но не отменяет проверку коллизии с
остальной вики (`check_collisions`, требование 2 задачи — см. ниже).

Якорь заметки — ОДИН, `## Текст` (по образцу `## Ответ`/`## Запись` у
FAQ/блогов): естественной второй границы внутри страницы нет — из 805
страниц лишь 52 несут внутренние `<h3>`, и то не переиспользуемо как
адрес (заголовки повторяются внутри одной процедуры — «Снятие»/
«Установка» на разных шагах). Поэтому внутренние подзаголовки ПОНИЖЕНЫ до
жирного абзаца (`**Название**`), а не переданы как заголовки Markdown:
иначе а) `run check` считал бы их адресами и требовал уникальности внутри
заметки, которой на живых страницах может не быть, б) они прошли бы через
`mirror._escape_headings` (гасит буквальные `#`/setext ВНУТРИ тела, чтобы
не оборвать секцию `## Текст` раньше времени) и превратились бы в
`\\###...` — видимый мусор. Полный список якорей — `docs/контракт-
зеркала.md`, тест-контракт — `tests/test_mirror_automn.py::
test_note_anchor_contract_is_exactly_h1_and_text_heading` (в одном файле с
остальными тестами модуля, не в `tests/test_anchor_contract.py`: тот файл
собирает три генератора вокруг ОБЩЕЙ SQLite-фикстуры, а этот источник
работает без базы вовсе — общая фикстура ему не подходит).

Таблицы: реальные таблицы спецификаций (692 страницы) стоят в исходнике
БЕЗ `<th>` (ни одного на весь корпус) и вперемешку с чисто РАЗМЕТОЧНЫМИ
таблицами (картинка + подпись рядом, тот же тег `<table>` ради вёрстки
2008 года). Разделяет их простой и надёжный на этом корпусе признак:
таблица БЕЗ единой картинки внутри — таблица данных, конвертируется в
GFM pipe-таблицу (первая строка — заголовок, раз `<th>` не бывает вовсе);
таблица С картинкой — вёрстка, разбирается ПОТОКОМ (ячейка за ячейкой, в
порядке чтения), а не таблицей — иначе картинка внутри ячейки markdown-
таблицы либо ломает разметку, либо картинка теряется. `colspan`/`rowspan`
раскрываются повторением значения по всем охваченным ячейкам (Markdown не
умеет объединять ячейки) — без этого числа терялись бы или съезжали по
столбцам, ровно та потеря, которой требование задачи прямо озабочено.

Картинки: адреса раздаются с поддоменов вида `s7.automn.ru`, среди них
ДВА иконки-хрома движка сайта (`images/warning.gif`, `images/attention.gif`
— почти на каждой странице, 662 и 755 вхождений на корпусе) — они
вырезаются целиком, без пометки об утрате (это разметка интерфейса, не
контент, тот же принцип, что и `attachments.KIND_CHROME` у форума).
ЛЮБОЙ другой адрес — контент (в т.ч. два адреса `images/subaru-*-05.jpg`
на обложках томов — проверено, это фотографии моделей, не хром): ищется в
манифесте добора (`data/automn/manifest.jsonl`, `url -> file`, статус
`ok`), копируется в `<wiki>/assets/<attachments.asset_name(url, data)>`
(та же функция и тот же общий каталог, что у форума/FAQ/блогов —
`mirror.copy_asset`) и вставляется позиционно; не найден — честная
пометка `mirror.IMAGE_LOST_TEMPLATE` (через `mirror.render_post_body`,
переиспользуется целиком, а не копируется). Скачивание картинок шло не
той же функцией именования, что кладёт файл в вики (`fetch_automn.
local_name` хэширует СЫРУЮ строку URL, `attachments.asset_name` — её же
`canonical_key`; это разные хэши по конструкции), поэтому картинка
сначала ИЩЕТСЯ на диске по адресу через манифест, а имя в вики считается
заново от найденных байт — то же самое разделение "найти" / "назвать",
что уже делает `archive_assets.find` для форума/FAQ/блогов.

Отсутствующие / не разобравшиеся страницы (нет `#contentblock` целиком —
структурный сюрприз, не встретился ни разу на корпусе, но чем-то другим
разбор молчаливо считать «нашёл заголовок» никогда не должен) получают
заметку с честной пометкой `mirror_blog.BODY_LOST` вместо тела — тот же
текст-плейсхолдер, что и у пустой записи блога, переиспользован буквально
(не дублирован новой константой): очистка цитирования (`pipeline.notes.
GENERATOR_PATTERNS`) уже вычищает этот литерал, значит для этого источника
отдельной регистрации не нужно — правило дословности не расходится, если
не заводить второй литерал с тем же смыслом.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from pipeline import check_mirror, mirror, mirror_blog

#: Ключ URL -> человекочитаемый ярлык тома, он же токен имени заметки.
#: Ровно два корня обхода (`tools/fetch_automn.py:ROOTS`) — открывать это
#: в перечень с запасом незачем, третий том потребует правки кода в любом
#: случае (новый URL-префикс, новая проверка).
MANUAL_LABELS = {"legacy-outback": "Legacy Outback", "forester": "Forester"}

#: Иконки интерфейса сайта — вырезаются без следа (см. докстринг модуля).
#: Сверено проходом по ВСЕМ картинкам корпуса под `/images/`: только эти
#: два имени встречаются на каждой странице (662/755 раз), два прочих
#: адреса `/images/subaru-*-05.jpg` — контент (фото модели на обложке
#: тома), поэтому правило — точное имя файла, а не сам каталог `/images/`.
_CHROME_IMAGE_NAMES = frozenset({"attention.gif", "warning.gif"})

#: Номер главы — читаемый префикс заголовка (`11.13`, `6.2.5`, до двух
#: вложенных уровней на живом корпусе). Две страницы обложки тома номера
#: не несут вовсе — `chapter_number` для них `None`, а не пустая строка,
#: чтобы не путать «нет номера» с «номер — пустая строка» ниже по стеку.
_CHAPTER_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+")

#: Символы, которые либо запрещены файловой системой (`\ / : * ? " < >`),
#: либо ломают вики-ссылку Obsidian (`# ^ [ ] |` — тот же список, что
#: называет докстринг `pipeline.mirror` про заголовочный якорь формы
#: `Пост <MID>`). Имя заметки — оно же цель сноски, поэтому оба вида риска
#: гасятся одной заменой: на пробел, с последующим схлопыванием пробелов.
_UNSAFE_NAME_CHARS = re.compile(r'[\\/:*?"<>|#^\[\]]')

_SKIP_TAGS = {"script", "style", "noscript"}
_BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "blockquote"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def normalize_name_component(text: str) -> str:
    """Один и тот же нормализатор для имени файла и текста алиаса — оба
    несут человекочитаемый заголовок, оба обязаны быть безопасны как
    вики-ссылка (см. `_UNSAFE_NAME_CHARS`)."""
    return _collapse_ws(_UNSAFE_NAME_CHARS.sub(" ", text or ""))


def _manual_from_url(url: str) -> str:
    path = urllib.parse.urlsplit(url or "").path
    for key in MANUAL_LABELS:
        if path.startswith("/subaru-%s/" % key):
            return key
    return ""


#: Заглушка заголовка — генераторный текст (задача 3 Ф3: любая строка-
#: плейсхолдер обязана быть модульной константой, а не встроенным
#: литералом, — `notes.GENERATOR_PATTERNS` вычищает её оттуда для проверки
#: дословности). На живом корпусе не встречается ни разу (все 805 страниц
#: несут `<h1>` — см. докстринг модуля), это защита от пустого/повреждённого
#: заголовка, а не ожидаемый случай.
NO_TITLE = "(без названия)"


def filename_for(manual: str, title: str) -> str:
    label = MANUAL_LABELS.get(manual, manual or "?")
    safe_title = normalize_name_component(title) or NO_TITLE
    return "Руководство %s %s.md" % (label, safe_title)


def _is_chrome_image_url(url: str) -> bool:
    path = urllib.parse.urlsplit(url or "").path
    return "/images/" in path and Path(path).name.lower() in _CHROME_IMAGE_NAMES


def _normalize_img_url(src: str, page_url: str) -> str:
    src = (src or "").strip()
    if not src:
        return ""
    url = urllib.parse.urljoin(page_url, src)
    url, _ = urllib.parse.urldefrag(url)
    return url


class _Ctx:
    """Контекст одного прохода разбора тела — счётчики таблиц идут сюда,
    а не в возвращаемое значение `_render`, чтобы не менять сигнатуру
    рекурсивного обхода ради статистики (см. `write_all`, где счётчики
    складываются в общий отчёт по всему корпусу)."""

    __slots__ = ("page_url", "tables_data", "tables_flat")

    def __init__(self, page_url: str):
        self.page_url = page_url
        self.tables_data = 0
        self.tables_flat = 0


def _cell_text(cell) -> str:
    """Текст ячейки таблицы ДАННЫХ: инлайновый (ссылки — текстом), без
    изображений (таблица данных по определению не содержит ни одного —
    см. `_render_table`), `|` экранирован, чтобы не порвать строку GFM."""
    parts: list[str] = []

    def walk(node):
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            parts.append(str(node).replace("\xa0", " "))
            return
        if not isinstance(node, Tag):
            return
        if node.name in _SKIP_TAGS:
            return
        if node.name == "br":
            parts.append(" ")
            return
        if node.name == "a" and node.get("href"):
            text = node.get_text(" ", strip=True)
            parts.append(text or node["href"])
            return
        for child in node.children:
            walk(child)

    walk(cell)
    return _collapse_ws("".join(parts)).replace("|", "\\|")


def _table_grid(rows: list) -> list[list[str]]:
    """`rows` (список `<tr>` СВОЕГО уровня таблицы) -> прямоугольная
    сетка текста. `colspan`/`rowspan` раскрываются повторением значения
    во ВСЕХ охваченных ячейках — единственный способ не потерять число
    и не сдвинуть остальные столбцы, раз Markdown не умеет объединять
    ячейки (см. докстринг модуля)."""
    grid: list[dict[int, str]] = []
    span: dict[int, tuple[str, int]] = {}  # col -> (текст, осталось строк)
    for tr in rows:
        row: dict[int, str] = {}
        cells = [c for c in tr.find_all(["td", "th"], recursive=False)]
        if not cells:
            cells = [c for c in tr.find_all(["td", "th"]) if c.find_parent("tr") is tr]
        ci = 0
        col = 0
        while ci < len(cells) or (span and col <= max(span)):
            if col in span:
                text, remaining = span[col]
                row[col] = text
                if remaining - 1 > 0:
                    span[col] = (text, remaining - 1)
                else:
                    del span[col]
                col += 1
                continue
            if ci >= len(cells):
                col += 1
                continue
            cell = cells[ci]
            ci += 1
            text = _cell_text(cell)
            colspan = max(1, _int_attr(cell, "colspan"))
            rowspan = max(1, _int_attr(cell, "rowspan"))
            for k in range(colspan):
                row[col + k] = text
                if rowspan > 1:
                    span[col + k] = (text, rowspan - 1)
            col += colspan
        grid.append(row)
    ncols = max((max(r.keys(), default=-1) for r in grid), default=-1) + 1
    return [[r.get(c, "") for c in range(ncols)] for r in grid]


def _int_attr(tag, name: str) -> int:
    try:
        return int(tag.get(name) or 1)
    except (TypeError, ValueError):
        return 1


def _render_table(table, parts: list[str], ctx: _Ctx) -> None:
    rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    has_image = any(
        not _is_chrome_image_url(_normalize_img_url(img.get("src") or "", ctx.page_url))
        for img in table.find_all("img")
    )
    if not rows:
        return
    if has_image:
        # Таблица-вёрстка (картинка + подпись): разбираем ПОТОКОМ, ячейка
        # за ячейкой в порядке чтения — не как markdown-таблицу (см.
        # докстринг модуля про риск потери/поломки разметки).
        ctx.tables_flat += 1
        parts.append("\n\n")
        for tr in rows:
            cells = [td for td in tr.find_all(["td", "th"]) if td.find_parent("tr") is tr]
            for td in cells:
                for child in td.children:
                    _render(child, parts, ctx)
                parts.append("\n\n")
        parts.append("\n\n")
        return

    ctx.tables_data += 1
    grid = _table_grid(rows)
    if not grid or not grid[0]:
        return
    ncols = len(grid[0])
    header, *body_rows = grid
    lines = ["| " + " | ".join(header) + " |",
             "| " + " | ".join(["---"] * ncols) + " |"]
    for row in body_rows:
        lines.append("| " + " | ".join(row) + " |")
    parts.append("\n\n" + "\n".join(lines) + "\n\n")


def _render(node, parts: list[str], ctx: _Ctx) -> None:
    if isinstance(node, Comment):
        return
    if isinstance(node, NavigableString):
        parts.append(str(node).replace("\xa0", " "))
        return
    if not isinstance(node, Tag):
        return
    name = node.name
    if name in _SKIP_TAGS:
        return
    if name == "br":
        parts.append("\n")
        return
    if name in _HEADING_TAGS:
        # Понижение до жирного абзаца, НЕ markdown-заголовок — см.
        # докстринг модуля (риск ложного якоря и `_escape_headings`).
        text = _collapse_ws(node.get_text(" ", strip=True))
        if text:
            parts.append("\n\n**%s**\n\n" % text)
        return
    if name == "table":
        _render_table(node, parts, ctx)
        return
    if name in _BLOCK_TAGS:
        parts.append("\n\n")
        for child in node.children:
            _render(child, parts, ctx)
        parts.append("\n\n")
        return
    if name == "a" and node.get("href"):
        text = node.get_text(" ", strip=True)
        href = node["href"]
        if not text and node.find("img"):
            for child in node.children:
                _render(child, parts, ctx)
            return
        parts.append("[%s](%s)" % (text, href) if text else href)
        return
    if name == "img":
        url = _normalize_img_url(node.get("src") or "", ctx.page_url)
        if url and not _is_chrome_image_url(url):
            parts.append("![](%s)" % url)
        return
    for child in node.children:
        _render(child, parts, ctx)


def parse_page(html: str, url: str) -> dict:
    """Разбирает ОДНУ HTML-страницу руководства.

    Возвращает `manual`, `title`, `chapter_number` (`None` — страница
    обложки тома без номера), `body_md` (markdown с позиционными
    маркерами `![](url)`, ещё БЕЗ подстановки картинок — её делает
    `write_all` через `mirror.render_post_body`, зная манифест) и `ok`
    (`False` — страница не похожа на страницу руководства: нет
    `#contentblock` или в нём нет тела известного вида).
    """
    soup = BeautifulSoup(html, "lxml")
    manual = _manual_from_url(url)
    cb = soup.find(id="contentblock")
    content = cb.find("div", class_="content") if cb else None
    header = content.find("div", class_="content-header") if content is not None else None
    h1 = header.find("h1") if header is not None else None
    title = _collapse_ws(h1.get_text(" ", strip=True)) if h1 is not None else ""
    art = None
    if content is not None:
        art = content.find("div", class_="article-content-text") or content.find("div", class_="content-text")

    chapter_number = None
    if title:
        m = _CHAPTER_NUM_RE.match(title)
        if m:
            chapter_number = m.group(1)

    body_md = ""
    ctx = _Ctx(url)
    if art is not None:
        parts: list[str] = []
        for child in art.children:
            _render(child, parts, ctx)
        body_md = "".join(parts)
        body_md = re.sub(r"[ \t]+\n", "\n", body_md)
        body_md = re.sub(r"\n{3,}", "\n\n", body_md)
        body_md = body_md.strip()

    return {
        "manual": manual,
        "title": title,
        "chapter_number": chapter_number,
        "body_md": body_md,
        "ok": art is not None and bool(title),
        "tables_data": ctx.tables_data,
        "tables_flat": ctx.tables_flat,
    }


def render_entry(page: dict, url: str, body: str) -> str:
    manual_label = MANUAL_LABELS.get(page["manual"], page["manual"] or "")
    title = page["title"] or NO_TITLE
    title_line = mirror._escape_headings(mirror._escape_wikilink_open(title))
    out = ["---",
           "руководство: %s" % mirror._yaml_dquote(manual_label),
           "номер: %s" % mirror._yaml_dquote(page["chapter_number"] or ""),
           "адрес: %s" % mirror._yaml_dquote(url),
           "aliases: [%s]" % mirror._yaml_dquote(title),
           "---", "",
           "# %s" % title_line, "",
           "## Текст", ""]
    out.append(body if body else mirror_blog.BODY_LOST)
    out.append("")
    return "\n".join(out)


def _load_ok_files(manifest_path: Path) -> dict[str, str]:
    """`url -> file` для строк со статусом `ok` — ПОСЛЕДНЯЯ запись в
    append-only манифесте побеждает (тот же приём, что `fetch_automn.
    load_done`: манифест только дописывается, повторная попытка того же
    URL идёт новой строкой ниже, а не правкой старой)."""
    manifest_path = Path(manifest_path)
    latest: dict[str, tuple[str, str]] = {}
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            latest[row["url"]] = (row.get("status", ""), row.get("file", ""))
    return {url: file for url, (status, file) in latest.items() if status == "ok" and file}


def write_all(pages_dir: Path, manifest_path: Path, out_dir: Path,
              assets_dir: Path | None = None) -> dict[str, int]:
    """Пишет заметку на каждую скачанную HTML-страницу манифеста и убирает
    заметки исчезнувших. Возвращает счётчики (штуки — требование задачи,
    не только "заметок: N"): страниц разобрано, заметок написано, картинок
    вставлено/утрачено, таблиц как данные/как поток, пустых страниц.

    Двухпроходная запись (сначала все имена, потом файлы на диск) — чтобы
    коллизия сгенерированного имени (см. докстринг модуля, `filename_for`)
    останавливала прогон ДО того, как зеркало частично перезаписано:
    "зеркало не тронуто" должно быть буквально верно, а не "тронуто
    наполовину, потом упало".
    """
    pages_dir = Path(pages_dir)
    out_dir = Path(out_dir)
    assets_dir = Path(assets_dir) if assets_dir is not None else out_dir / "assets"
    url_to_file = _load_ok_files(manifest_path)
    html_urls = sorted(url for url, f in url_to_file.items() if f.endswith(".html"))

    stats = {"страниц": 0, "заметок": 0, "картинок_вставлено": 0, "картинок_утрачено": 0,
              "таблиц_данных": 0, "таблиц_разложено": 0, "пустых": 0}

    parsed: list[tuple[str, dict]] = []
    names: dict[str, str] = {}
    for url in html_urls:
        stats["страниц"] += 1
        html_path = pages_dir / url_to_file[url]
        html = html_path.read_text(encoding="utf-8", errors="replace")
        page = parse_page(html, url)
        if not page["ok"]:
            stats["пустых"] += 1
        name = filename_for(page["manual"], page["title"] or url)
        if name in names:
            raise RuntimeError(
                "коллизия имени заметки «%s»: страницы «%s» и «%s» дают одно и то же имя. "
                "Зеркало не тронуто: %s" % (name, names[name], url, out_dir))
        names[name] = url
        stats["таблиц_данных"] += page["tables_data"]
        stats["таблиц_разложено"] += page["tables_flat"]
        parsed.append((name, page, url))

    out_dir.mkdir(parents=True, exist_ok=True)
    used_assets: set[str] = set()
    written: set[str] = set()
    for name, page, url in parsed:
        image_urls = list(dict.fromkeys(mirror._IMG_MD.findall(page["body_md"]))) if page["body_md"] else []
        images_by_url: dict[str, dict] = {}
        for img_url in image_urls:
            local = None
            src_file = url_to_file.get(img_url)
            if src_file:
                src_path = pages_dir / src_file
                if src_path.exists():
                    local = mirror.copy_asset(img_url, src_path, assets_dir)
            if local:
                used_assets.add(local.rsplit("/", 1)[-1])
                stats["картинок_вставлено"] += 1
            else:
                stats["картинок_утрачено"] += 1
            images_by_url[img_url] = {"local_path": local}

        body = mirror.render_post_body(page["body_md"], images_by_url) if page["body_md"] else ""
        (out_dir / name).write_text(render_entry(page, url, body), encoding="utf-8")
        written.add(name)
        stats["заметок"] += 1

    stale = [p for p in sorted(out_dir.glob("Руководство *.md")) if p.name not in written]
    if len(stale) > stats["заметок"]:
        raise RuntimeError(
            "отказ убирать заметки «Руководство»: записано %d, под удаление попало %d. "
            "Похоже, манифест не описывает это зеркало (пустой/не тот путь). "
            "Зеркало не тронуто: %s" % (stats["заметок"], len(stale), out_dir))
    for path in stale:
        path.unlink()
    mirror.prune_assets(assets_dir, used_assets, stats["заметок"])
    return stats


def check_collisions(wiki_root: Path) -> dict[str, list[str]]:
    """Требование 2: имя заметки — функция ОДНОЙ страницы, но обязано быть
    сверено с уже существующими заметками/алиасами вики (иначе сноска на
    совпавшее имя станет неоднозначной). Готовая проверка —
    `check_mirror.title_collisions`, а не своя копия: та же функция уже
    используется `pipeline.articles.build`/`pipeline.verify.check`.

    Возвращает `{имя заметки «Руководство»: [ключи совпавших заметок]}` —
    только непустые находки.
    """
    wiki_root = Path(wiki_root)
    notes, by_name = check_mirror.build_notes_index(wiki_root)
    alias_index = check_mirror.build_alias_index(notes)
    found: dict[str, list[str]] = {}
    for key in notes:
        # `Path.name`, НЕ `.stem`: `key` уже без расширения (`build_notes_
        # index` снимает его через `with_suffix("")`), а `.stem` снова
        # отрезает "суффикс" — и ошибочно принимает точку номера главы
        # (`11.13`) за расширение файла, обрезая заголовок до "...11".
        name = Path(key).name
        if not name.startswith("Руководство "):
            continue
        title = name[len("Руководство "):]
        # Имя несёт токен тома первым словом-двумя ("Legacy Outback "/
        # "Forester ") — коллизия ищется по САМОМУ ЗАГОЛОВКУ страницы
        # (без токена тома), потому что именно так его напишет автор
        # статьи, ссылаясь по алиасу by design (см. докстринг модуля).
        for label in MANUAL_LABELS.values():
            if title.startswith(label + " "):
                title = title[len(label) + 1:]
                break
        collisions = check_mirror.title_collisions(title, by_name, alias_index, own_key=key)
        # Коллизия МЕЖДУ ДВУМЯ ТОМАМИ руководства (одна и та же глава,
        # «11.13»/«Спецификации» и т.п., есть и у Legacy Outback, и у
        # Forester — 46 таких пар на живом корпусе, см. докстринг модуля)
        # — ИЗВЕСТНОЕ и задокументированное свойство источника, а не находка
        # для устранения: сноска на голый алиас в этом случае действительно
        # неоднозначна, но лечится она НЕ здесь (правкой заголовка одной
        # главы), а тем, что автор статьи обязан целиться полным именем
        # заметки (`Руководство <том> <глава>`), а не одним алиасом. Отчёт
        # оставляет только коллизии с ЧУЖИМИ разделами вики (форум/FAQ/
        # блоги/статьи) — вот они и требуют внимания требования 2.
        outside = [k for k in collisions if not Path(k).name.startswith("Руководство ")]
        if outside:
            found[title] = outside
    return found
