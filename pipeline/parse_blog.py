"""Парсер страниц раздела блогов (Ф2, задача 7).

Движок Bitrix "Blog". Разметка семейства `blog-*` (см. task-5-report.md,
`fetch_site.blogs_content_probe`): `page=post` — отдельная запись,
`page=blog` (+ `category`/`year`/`month`/`day`/`PAGEN_1`/...) — лента,
несколько записей на одной странице, каждая обёрнута в тот же `div.blog-
post`, что и одиночная запись. Разведка задачи 7 (проверено на всём
скачанном корпусе — 1078 страниц, `status=ok`, см. task-7-report.md):

- Признак "это полная запись, а не выдержка ленты" — НЕ URL и не число
  блоков на странице, а форма заголовка ВНУТРИ конкретного блока:
  `<h2 class="blog-post-title"><span>...</span></h2>` — полная запись
  (заголовок текстом), `<h2 class="blog-post-title"><a href="...post_id=
  N">...</a></h2>` — выдержка (заголовок ссылкой на страницу записи).
  Проверено на ВСЕХ 488 полных страницах (`page=post`) и на ВСЕХ 1168
  блоках всех лент — ни одного исключения ни в одну сторону. Это надёжнее,
  чем классификация по `kind` плана (`fetch_site._blogs_kind`), потому что
  443 из 590 скачанных страниц-лент несут ровно ОДИН блок — по числу блоков
  их было бы не отличить от полной записи.
- `post_id` (номер записи) НИГДЕ не встречается в HTML полной страницы —
  только в URL запроса (`page=post&...&post_id=N`), в отличие от FAQ, где
  `ELEMENT_ID` дублируется в теле страницы (ссылка "печать", `backurl`).
  Значит `parse_post`/`parse_excerpt_block` обязаны знать URL страницы —
  без него разбор попросту невозможен, а не просто менее надёжен.
- `post_id` УНИКАЛЕН только ВНУТРИ одного блога (слага `blog=`) — на живом
  корпусе 10 номеров пересекаются между блогами `remont`/`remontSubaru`
  (общий счётчик Bitrix, начатый заново после переименования блога — то же
  явление, что и (engine, nr) у FAQ в задаче 6). Первичный ключ — пара
  (blog, post_id), так же как там.
- Часть записей архивирована НЕСКОЛЬКИМИ страницами с разными `pagen=N` —
  это НЕ дубли и не разные записи, а постраничная разбивка КОММЕНТАРИЕВ под
  одной и той же записью (страница без `pagen` — первая "страница"
  комментариев, `pagen=2..N` — следующие, текст/заголовок записи на всех
  идентичен). На живом корпусе так устроено 4 записи (32 URL, 16 "лишних"
  сверх 4 канонических). `merge_paginated` схлопывает такую группу в одну
  запись, комментарии — объединением по `comment_id` (см. её докстринг).
- Изображения аватара (`/upload/blog/avatar/...` у самой записи и
  `/upload/resize_cache/blog/avatar/...` у комментария) — декоративная
  картинка профиля, а не контент: у 46 из 488 полных записей и у части
  комментариев (283 из 734 несут хоть один `<img>`, из них 275 — смайлы
  движка, остальные — почти все именно такие аватарки). Срезаются целиком
  ДО рендера в markdown (`_strip_avatars`) — в отличие от смайлов движка
  (`bitrix/images/blog/smile/...`), которые остаются в тексте как обычная
  картинка и отсеиваются позже, при генерации заметки, тем же правилом
  `attachments.classify`, что и у форума/FAQ (см. `pipeline.mirror.
  render_post_body`) — здесь они попросту исключаются из `images` записи,
  чтобы не try'иться найти файл для того, чего никогда не было отдельным
  файлом.
"""
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from pipeline import assets_state, attachments, fetch_site, html_text

_LOG = logging.getLogger(__name__)

_BASE = "http://subaru-faq.ru/blogs/index.php"

# То же экранирование, что и в parse_faq._IMG_MD/_absolutize_images — URL
# внутри `![]()` может содержать один уровень вложенных скобок.
_IMG_MD = re.compile(r"!\[\]\(((?:[^()]|\([^()]*\))*)\)")

# Признак декоративной аватарки — своя (запись) и уменьшенная (комментарий)
# версии одного и того же каталога `upload/blog/avatar/...` (см. докстринг
# модуля). Проверяется по подстроке пути, а не по точному префиксу — оба
# варианта содержат "/avatar/" и не встречаются больше нигде на корпусе.
_AVATAR_MARKER = "/avatar/"

_PADDING_RE = re.compile(r"padding-left:\s*([\d.]+)em")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _absolutize_images(markdown: str, base: str = _BASE) -> str:
    return _IMG_MD.sub(lambda m: "![](%s)" % urllib.parse.urljoin(base, m.group(1)), markdown)


def _strip_avatars(tag: Tag) -> None:
    """Вырезает декоративные картинки аватара из DOM ДО рендера в markdown
    (см. докстринг модуля) — они не должны оставить по себе даже честную
    пометку об утрате, потому что отдельным файлом с самостоятельной
    ценностью никогда не были.
    """
    for img in tag.find_all("img"):
        src = img.get("data-bx-image") or img.get("src") or ""
        if _AVATAR_MARKER in src:
            img.extract()


def _url_key(url: str) -> tuple[str, int | None, int | None]:
    """`(blog, post_id, pagen)` из URL записи — единственный источник этих
    полей (см. докстринг модуля, "post_id нигде не встречается в HTML").
    """
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    blog = qs.get("blog", [""])[0]
    pid = qs.get("post_id", [""])[0]
    pagen = qs.get("pagen", [""])[0]
    return (blog, int(pid) if pid.isdigit() else None,
            int(pagen) if pagen.isdigit() else None)


def _extract_tags(block: Tag) -> list[str]:
    tag_div = block.select_one("div.blog-post-tag")
    if tag_div is None:
        return []
    return [_clean(a.get_text(" ", strip=True)) for a in tag_div.find_all("a") if a.get_text(strip=True)]


def _content_images(inner_html: str) -> list[str]:
    """Абсолютные адреса содержательных картинок тела — смайлы движка
    (`attachments.classify` -> `chrome`) исключены (см. докстринг модуля):
    их не нужно искать в архиве, а честная пометка об утрате при рендере
    заметки для них и так не строится (то же правило, что у форума/FAQ).
    """
    out = []
    for u in html_text.images(inner_html):
        abs_u = urllib.parse.urljoin(_BASE, u)
        if attachments.classify(abs_u) != attachments.KIND_CHROME:
            out.append(abs_u)
    return out


def _render_block(block: Tag) -> tuple[str, list[str], bool]:
    """Тело блока (`div.blog-post-content`) -> `(markdown, images, truncated)`.

    Общая для полной записи и для выдержки ленты — разметка `blog-post-
    content` у них идентична (см. докстринг модуля). `truncated` — истинно,
    если в теле была ссылка "Читать подробнее..." (`a.blog-postmore-link`,
    только у выдержек лент, но проверка безвредна и для полных записей).
    """
    content = block.select_one("div.blog-post-content")
    if content is None:
        return "", [], False
    more_link = content.select_one("a.blog-postmore-link")
    truncated = more_link is not None
    if more_link is not None:
        more_link.extract()
    _strip_avatars(content)
    inner = content.decode_contents()
    body_md = _absolutize_images(html_text.to_markdown(inner))
    images = _content_images(inner)
    return body_md, images, truncated


@dataclass
class BlogComment:
    comment_id: int
    parent_id: int | None
    depth: int
    author: str
    posted_at: str
    text_md: str


@dataclass
class BlogPost:
    blog: str
    post_id: int
    title: str
    author: str
    posted_at: str
    body_md: str
    images: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    source_url: str = ""
    snapshot_ts: str = ""
    is_excerpt: bool = False
    truncated: bool = False
    comments: list[BlogComment] = field(default_factory=list)
    declared_comments: int | None = None


def _parse_comment(anchor: Tag, comment_div: Tag) -> BlogComment | None:
    name = anchor.get("name")
    if not name or not name.isdigit():
        return None
    comment_id = int(name)

    author_div = comment_div.select_one("div.blog-author")
    author = _clean(author_div.get_text(" ", strip=True)) if author_div else ""
    date_div = comment_div.select_one("div.blog-comment-date")
    posted_at = _clean(date_div.get_text(" ", strip=True)) if date_div else ""

    depth = 0
    m = _PADDING_RE.search(comment_div.get("style") or "")
    if m:
        depth = int(round(float(m.group(1)) / 2.5))

    parent_id = None
    parent_link = comment_div.select_one("span.blog-comment-parent a")
    if parent_link is not None:
        href = parent_link.get("href") or ""
        if href.startswith("#") and href[1:].isdigit():
            parent_id = int(href[1:])

    text_md = ""
    content = comment_div.select_one("div.blog-comment-content")
    if content is not None:
        meta = content.select_one("div.blog-comment-meta")
        if meta is not None:
            meta.extract()
        _strip_avatars(content)
        text_md = _absolutize_images(html_text.to_markdown(content.decode_contents()))

    return BlogComment(comment_id=comment_id, parent_id=parent_id, depth=depth,
                        author=author, posted_at=posted_at, text_md=text_md)


def _parse_comments(soup: BeautifulSoup) -> list[BlogComment]:
    """Комментарии единственного блока `div.blog-comments` страницы записи
    (ленты его не несут вовсе — см. докстринг модуля). Каждый комментарий —
    `<a name="ID"></a>`, СЛЕДОМ его родной `<div class="blog-comment">`
    (проверено на всём корпусе полных записей). Имя `"0"` — placeholder формы
    добавления нового комментария верхнего уровня, не комментарий: у него
    нет родного `div.blog-comment` рядом, `find_next_sibling` естественно
    вернёт `None`/чужой тег, и запись будет пропущена без специального кейса.
    """
    container = soup.select_one("div.blog-comments")
    if container is None:
        return []
    out = []
    for anchor in container.find_all("a", attrs={"name": True}):
        sib = anchor.find_next_sibling()
        if sib is None or sib.name != "div" or "blog-comment" not in (sib.get("class") or []):
            continue
        c = _parse_comment(anchor, sib)
        if c is not None:
            out.append(c)
    return out


def _declared_comment_count(block: Tag) -> int | None:
    """Число из счётчика "Комментариев: N" рядом с блоком — НЕ надёжный
    источник истины (разведка задачи 7: на 164 нераспагинированных полных
    записях расходится с реально распарсенным числом в 18 случаях из 164,
    причём в обе стороны, а на страницах, разбитых по `pagen`, счётчик
    вовсе не отражает ни число комментариев НА этой странице, ни их
    итоговое число после слияния — см. task-7-report.md). Сохраняется
    только для честного упоминания в отчёте, не для арифметики "потеряно".
    """
    span = block.select_one("span.blog-post-comments-link")
    if span is None:
        return None
    m = re.search(r"(\d+)", span.get_text(" ", strip=True))
    return int(m.group(1)) if m else None


def parse_post(html: str, url: str) -> BlogPost | None:
    """Разбирает страницу отдельной записи (`page=post`). `None` — страница
    не несёт ни одного блока записи (сбойный/пустой снимок) или `post_id`
    не удалось узнать из URL (см. докстринг модуля).
    """
    blog, post_id, _pagen = _url_key(url)
    if post_id is None or not blog:
        return None
    soup = BeautifulSoup(html, "lxml")
    block = soup.select_one("div.blog-post")
    if block is None:
        return None
    h2 = block.select_one("h2.blog-post-title")
    title = _clean(h2.get_text(" ", strip=True)) if h2 else ""
    author_div = block.select_one("div.blog-author")
    author = _clean(author_div.get_text(" ", strip=True)) if author_div else ""
    date_div = block.select_one("div.blog-post-date")
    posted_at = _clean(date_div.get_text(" ", strip=True)) if date_div else ""
    # `tags`/счётчик комментариев ищутся ПО ВСЕМУ ДОКУМЕНТУ, а не внутри
    # `block` — находка разведки задачи 7: у 79/183 полных страниц с тегами
    # (и у 308/488 с `blog-post-meta`) незакрытый тег где-то в теле
    # (`<table>` без пары — см. фикстуру `blog_post_with_tags.html`)
    # заставляет lxml закрыть `div.blog-post` РАНЬШЕ, чем реально кончается
    # разметка, и `blog-post-meta`/`blog-post-tag` (они идут в вёрстке
    # СЛЕДОМ за `blog-post-content`) оказываются вне блока. На страницах
    # `page=post` блок всегда ровно один (проверено на всех 488 — см.
    # докстринг модуля), поэтому поиск по всему документу однозначен и
    # безопасен; на лентах (`parse_listing_excerpts`) блоков много, там то
    # же самое смещение не встретилось НИ РАЗУ (проверено на всех 1168
    # блоках) — там поиск остаётся строго внутри своего блока.
    tags = _extract_tags(soup)
    body_md, images, _truncated_marker = _render_block(block)
    declared = _declared_comment_count(soup)
    comments = _parse_comments(soup)

    return BlogPost(blog=blog, post_id=post_id, title=title, author=author, posted_at=posted_at,
                     body_md=body_md, images=images, tags=tags, source_url=url,
                     comments=comments, declared_comments=declared)


def parse_listing_excerpts(html: str, url: str) -> list[BlogPost]:
    """Разбирает страницу ленты (`page=blog` + категория/календарь/история)
    в список выдержек — по одной на каждый блок `div.blog-post` С заголовком-
    ССЫЛКОЙ (см. докстринг модуля: заголовок-`<span>` в ленте не встретился
    ни разу, но проверка на всякий случай — если он всё же появится,
    значит это полная запись, просочившаяся не туда, и её надёжнее
    пропустить, чем разобрать неправильно). `post_id`/`blog` — из `href`
    ссылки заголовка (у самой страницы ленты `post_id` в URL может не быть
    вовсе). Комментарии выдержкам не положены — лента их не показывает.
    """
    soup = BeautifulSoup(html, "lxml")
    out = []
    for block in soup.select("div.blog-post"):
        h2 = block.select_one("h2.blog-post-title")
        link = h2.find("a") if h2 else None
        if link is None or not link.get("href"):
            continue
        blog, post_id, _pagen = _url_key(urllib.parse.urljoin(_BASE, link["href"]))
        if post_id is None or not blog:
            continue
        # Текст ссылки в ленте иногда усечён вёрсткой — атрибут `title`
        # несёт полный заголовок и не короче текста ни разу на корпусе.
        title = _clean(link.get("title") or "") or _clean(link.get_text(" ", strip=True))
        author_div = block.select_one("div.blog-author")
        author = _clean(author_div.get_text(" ", strip=True)) if author_div else ""
        date_div = block.select_one("div.blog-post-date")
        posted_at = _clean(date_div.get_text(" ", strip=True)) if date_div else ""
        tags = _extract_tags(block)
        body_md, images, truncated = _render_block(block)
        declared = _declared_comment_count(block)
        out.append(BlogPost(blog=blog, post_id=post_id, title=title, author=author, posted_at=posted_at,
                             body_md=body_md, images=images, tags=tags, source_url=url,
                             is_excerpt=True, truncated=truncated, declared_comments=declared))
    return out


def merge_paginated(pages: list[BlogPost]) -> BlogPost:
    """Схлопывает несколько страниц одной записи, разбитой по `pagen`
    (постраничные комментарии, см. докстринг модуля) в одну запись.

    Заголовок/автор/дата/тело/теги/картинки — с КАНОНИЧЕСКОЙ страницы (без
    `pagen` в URL); если её среди `pages` почему-то нет (страница-без-pagen
    не скачалась) — с той, где `pagen` меньше всего (наиболее вероятный
    источник полного текста). Комментарии — объединение по `comment_id` по
    ВСЕМ страницам группы (на живом корпусе диапазоны `comment_id` разных
    `pagen` не пересекаются — проверено, но `dict` по `comment_id` схлопнул
    бы и пересечение, если оно всё же где-то есть), результат отсортирован
    по `comment_id` (числа возрастают со временем — устойчивый порядок и
    без разбора русской даты).
    """
    def _pagen_of(p: BlogPost) -> int:
        _b, _pid, pagen = _url_key(p.source_url)
        return pagen if pagen is not None else 0

    canonical = min(pages, key=_pagen_of)
    by_id: dict[int, BlogComment] = {}
    for p in pages:
        for c in p.comments:
            by_id[c.comment_id] = c
    merged_comments = [by_id[k] for k in sorted(by_id)]
    return BlogPost(blog=canonical.blog, post_id=canonical.post_id, title=canonical.title,
                     author=canonical.author, posted_at=canonical.posted_at, body_md=canonical.body_md,
                     images=canonical.images, tags=canonical.tags, source_url=canonical.source_url,
                     comments=merged_comments, declared_comments=canonical.declared_comments)


def _plan_by_url(site_root: Path) -> dict[str, dict]:
    try:
        plan = fetch_site.load_plan("blogs", root=site_root)
    except FileNotFoundError:
        return {}
    return {item["url"]: item for item in plan}


def load_all(site_root: Path, site_manifest: Path, conn) -> dict[str, int]:
    """Разбирает все успешно скачанные страницы блогов и пишет их в таблицы
    `blog_posts`/`blog_images`/`blog_comments`.

    Источник состояния — тот же манифест добора, что и у FAQ (`fetch_site.
    fetch_all`): только `status == "ok"` под `/blogs/`. Отсутствие
    `manifest-site.jsonl`/плана (свежий чекаут без добора) — НЕ ошибка,
    как и у `parse_faq.load_all`.

    Порядок: сперва все страницы `page=post` группируются по `(blog,
    post_id)` и схлопываются `merge_paginated` — это ПОЛНЫЕ записи; затем
    все страницы лент разбираются в выдержки, и только те, чей `(blog,
    post_id)` НЕ встретился среди полных записей, становятся отдельными
    заметками-выдержками (см. докстринг модуля и `mirror_blog.py`). Среди
    нескольких выдержек одной записи (запись показана в нескольких лентах)
    побеждает НЕ обрезанная "Читать подробнее...", если такая есть, иначе
    самая длинная по тексту — тай-брейк сортировкой URL для детерминизма.
    """
    stats = {"pages_post": 0, "pages_listing": 0, "posts_parsed": 0, "pagen_groups": 0,
              "pagen_pages_merged": 0, "excerpt_candidates": 0, "excerpt_only": 0,
              "excerpt_used": 0, "excerpt_truncated": 0, "empty_body": 0, "images": 0,
              "comments": 0, "unparsed": 0}
    known = assets_state.load(site_manifest)
    plan_by_url = _plan_by_url(site_root)

    blog_urls = sorted(url for url, rec in known.items()
                        if "/blogs/" in url and rec.get("status") == "ok" and rec.get("path"))

    def _kind(url: str) -> str:
        item = plan_by_url.get(url)
        if item is not None:
            return item.get("kind", "listing")
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        return "post" if qs.get("page", [None])[0] == "post" else "listing"

    groups: dict[tuple, list[BlogPost]] = {}
    excerpt_groups: dict[tuple, list[BlogPost]] = {}
    ts_by_url: dict[str, str] = {}

    for url in blog_urls:
        rec = known[url]
        item = plan_by_url.get(url)
        ts_by_url[url] = item.get("ts", "") if item else ""
        path = Path(site_root) / rec["path"]
        html = path.read_bytes().decode("cp1251", "replace")
        kind = _kind(url)
        if kind == "post":
            stats["pages_post"] += 1
            entry = parse_post(html, url)
            if entry is None:
                stats["unparsed"] += 1
                _LOG.warning("blogs: не удалось разобрать %s (%s)", url, rec["path"])
                continue
            groups.setdefault((entry.blog, entry.post_id), []).append(entry)
        else:
            stats["pages_listing"] += 1
            for entry in parse_listing_excerpts(html, url):
                excerpt_groups.setdefault((entry.blog, entry.post_id), []).append(entry)

    final: dict[tuple, BlogPost] = {}
    for key, pages in groups.items():
        merged = merge_paginated(pages) if len(pages) > 1 else pages[0]
        if len(pages) > 1:
            stats["pagen_groups"] += 1
            stats["pagen_pages_merged"] += len(pages)
        final[key] = merged
        final[key].snapshot_ts = ts_by_url.get(merged.source_url, "")

    stats["posts_parsed"] = len(final)

    stats["excerpt_candidates"] = sum(len(v) for v in excerpt_groups.values())
    for key, candidates in excerpt_groups.items():
        if key in final:
            continue
        stats["excerpt_only"] += 1
        not_truncated = [c for c in candidates if not c.truncated]
        pool = not_truncated or candidates
        # Длиннейшее тело побеждает; тай-брейк — сортировка по URL, чтобы
        # результат был детерминирован независимо от порядка обхода словаря.
        best = sorted(pool, key=lambda c: (len(c.body_md), c.source_url))[-1]
        if best.truncated:
            stats["excerpt_truncated"] += 1
        stats["excerpt_used"] += 1
        best.snapshot_ts = ts_by_url.get(best.source_url, "")
        final[key] = best

    for (blog, post_id), entry in final.items():
        if not entry.body_md.strip():
            stats["empty_body"] += 1
        conn.execute(
            "INSERT INTO blog_posts(blog, post_id, title, author, posted_at, body_md, tags, "
            "source_url, snapshot_ts, is_excerpt, truncated, declared_comments) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(blog, post_id) DO UPDATE SET title=excluded.title, author=excluded.author, "
            "posted_at=excluded.posted_at, body_md=excluded.body_md, tags=excluded.tags, "
            "source_url=excluded.source_url, snapshot_ts=excluded.snapshot_ts, "
            "is_excerpt=excluded.is_excerpt, truncated=excluded.truncated, "
            "declared_comments=excluded.declared_comments",
            (blog, post_id, entry.title, entry.author, entry.posted_at, entry.body_md,
             json.dumps(entry.tags, ensure_ascii=False), entry.source_url,
             entry.snapshot_ts, int(entry.is_excerpt), int(entry.truncated), entry.declared_comments))

        conn.execute("DELETE FROM blog_images WHERE blog = ? AND post_id = ?", (blog, post_id))
        for img_url in entry.images:
            conn.execute("INSERT INTO blog_images(blog, post_id, url, local_path) VALUES (?,?,?,NULL)",
                         (blog, post_id, img_url))
            stats["images"] += 1

        conn.execute("DELETE FROM blog_comments WHERE blog = ? AND post_id = ?", (blog, post_id))
        for c in entry.comments:
            conn.execute(
                "INSERT INTO blog_comments(blog, post_id, comment_id, parent_id, depth, author, "
                "posted_at, text_md) VALUES (?,?,?,?,?,?,?,?)",
                (blog, post_id, c.comment_id, c.parent_id, c.depth, c.author, c.posted_at, c.text_md))
            stats["comments"] += 1

    conn.commit()
    return stats
