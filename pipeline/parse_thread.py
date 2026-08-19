"""Парсер страниц тем форума (read_<FID>_<TID>_<страница>.html).

Извлекает посты со страницы темы: автора, дату, номер поста, HTML/markdown/
plain-text тела и список картинок. `mid` (message id) — устойчивый
идентификатор поста, на который будут ссылаться сноски базы знаний.

Подпись пользователя (`div.forum-user-signature`) — не текст поста, это
соседний с `div.forum-post-text` элемент внутри той же таблицы; извлекаем
тело строго из `forum-post-text`, поэтому подпись в текст не попадает.
"""
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from pipeline import html_text


@dataclass
class Post:
    mid: int
    author: str
    author_uid: int | None
    posted_at: str
    number: str
    html: str
    markdown: str
    text: str
    images: list[str] = field(default_factory=list)
    edited_by: str | None = None
    edited_at: str | None = None


@dataclass
class ThreadPage:
    title: str
    posts: list[Post]


def _dt(ru: str) -> str:
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}:\d{2}:\d{2})", ru or "")
    return "%s-%s-%s %s" % (m.group(3), m.group(2), m.group(1), m.group(4)) if m else ""


def parse(html: str) -> ThreadPage:
    soup = BeautifulSoup(html, "lxml")
    title_node = soup.select_one("div.forum-header-title span")
    title = title_node.get_text(" ", strip=True) if title_node else ""
    posts: list[Post] = []
    for table in soup.select('table[id^="message"]'):
        m = re.match(r"message(\d+)$", table.get("id", ""))
        if not m:
            continue
        mid = int(m.group(1))
        body = table.select_one("div.forum-post-text")
        if body is None:
            continue
        user_link = table.select_one("div.forum-user-name a")
        uid_m = re.search(r"UID=(\d+)", user_link.get("href", "")) if user_link else None
        # Часть постов (спам-аккаунт, удалённый пользователь) не имеет ссылки
        # на профиль — div.forum-user-name содержит только текст без <a>.
        # Без фолбэка автор терялся бы полностью (author="").
        author_node = user_link or table.select_one("div.forum-user-name")
        date_node = table.select_one("div.forum-post-date span")
        num_node = table.select_one("div.forum-post-number a")
        ed_user = table.select_one("span.forum-post-lastedit-user")
        ed_date = table.select_one("span.forum-post-lastedit-date")
        inner = body.decode_contents()
        # HTML тела поста разбирается один раз: text — производная от
        # markdown, а не второй проход по тому же HTML.
        markdown = html_text.to_markdown(inner)
        posts.append(Post(
            mid=mid,
            author=author_node.get_text(" ", strip=True) if author_node else "",
            author_uid=int(uid_m.group(1)) if uid_m else None,
            posted_at=_dt(date_node.get_text(" ", strip=True) if date_node else ""),
            number=num_node.get_text(" ", strip=True) if num_node else "",
            html=inner,
            markdown=markdown,
            text=html_text.plain_text_from_markdown(markdown),
            images=html_text.images(inner),
            edited_by=ed_user.get_text(" ", strip=True) if ed_user else None,
            edited_at=_dt(ed_date.get_text(" ", strip=True)) if ed_date else None,
        ))
    return ThreadPage(title=title, posts=posts)
