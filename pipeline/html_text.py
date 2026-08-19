"""Конвертер HTML тела поста форума в Markdown и plain-text.

Вход — HTML содержимого `div.forum-post-text` (без подписи пользователя,
это ответственность вызывающего кода). Кодировка на входе — уже str
(декодирование cp1251 происходит выше по стеку, при чтении сырых страниц).
"""
import re

from bs4 import BeautifulSoup, NavigableString, Tag


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def images(html: str) -> list[str]:
    """Полноразмерные адреса картинок: data-bx-src, если есть, иначе src."""
    out = []
    for img in _soup(html).find_all("img"):
        url = img.get("data-bx-src") or img.get("src")
        if url:
            out.append(url)
    return out


# Теги, чьё содержимое никогда не является текстом поста: встроенный JS
# видео-плееров (напр. bx_flv_player) и текстовая заглушка "отключен
# JavaScript" в noscript. Без этого фильтра их содержимое дословно
# протекает в markdown/plain_text как мусор.
_SKIP_TAGS = {"script", "style", "noscript"}


def _render(node, parts: list[str]) -> None:
    if isinstance(node, NavigableString):
        parts.append(str(node).replace("\xa0", " "))
        return
    if not isinstance(node, Tag):
        return
    if node.name in _SKIP_TAGS:
        return
    if node.name == "br":
        parts.append("\n")
        return
    if node.name == "table":
        # Форум пережил смену движка, и цитаты в нём двух видов:
        #   - Bitrix: <table class="forum-quote">, вся цитата в первой ячейке;
        #   - легаси (пре-Bitrix, 877 постов в 131 теме): таблица без класса,
        #     атрибуция в <td class="SmallText">, тело цитаты в <td class="quote">.
        # Второй вид раньше не распознавался вовсе — цитата приезжала плоским
        # текстом. Пока тело заметки было plain_text, это было не видно (маркеры
        # снимались у всех); с переходом на markdown такие посты остались бы
        # единственными, где чужие слова неотличимы от слов автора.
        classes = node.get("class") or []
        legacy_cell = None if "forum-quote" in classes else node.find("td", class_="quote")
        if "forum-quote" in classes or legacy_cell is not None:
            inner: list[str] = []
            if "forum-quote" in classes:
                cell = node.find("td")
                if cell:
                    for child in cell.children:
                        _render(child, inner)
            else:
                # Строки легаси-таблицы дают отдельные строки цитаты (иначе
                # атрибуция слипается с первой строкой тела). Берём только СВОИ
                # строки и ячейки: вложенная цитата — отдельная таблица, её
                # обработает та же ветка рекурсивно и добавит второй уровень `>`.
                for tr in node.find_all("tr"):
                    if tr.find_parent("table") is not node:
                        continue
                    row: list[str] = []
                    for td in tr.find_all("td"):
                        if td.find_parent("tr") is not tr:
                            continue
                        for child in td.children:
                            _render(child, row)
                    inner.append("".join(row))
                    inner.append("\n")
            body = "".join(inner).strip()
            quoted = "\n".join("> " + line.strip() for line in body.split("\n") if line.strip())
            parts.append("\n" + quoted + "\n")
            return
    if node.name == "a" and node.get("href"):
        text = node.get_text(" ", strip=True)
        if not text and node.find("img"):
            # Картинка-превью, обёрнутая в ссылку на страницу хостинга
            # изображений (лайтбокс radikal.ru/qip.ru и т.п.) — сама ссылка
            # ведёт не на изображение, а на HTML-страницу. Рендерим как
            # картинку, а не как голый URL, иначе изображение бесследно
            # исчезает из markdown/plain_text (при этом images() его всё
            # равно находит — получался бы разнобой).
            for child in node.children:
                _render(child, parts)
            return
        parts.append("[%s](%s)" % (text, node["href"]) if text else node["href"])
        return
    if node.name == "img":
        url = node.get("data-bx-src") or node.get("src") or ""
        parts.append("![](%s)" % url)
        return
    for child in node.children:
        _render(child, parts)


def to_markdown(html: str) -> str:
    parts: list[str] = []
    for child in _soup(html).children:
        _render(child, parts)
    text = "".join(parts)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def plain_text_from_markdown(md: str) -> str:
    """Плоский текст из уже посчитанного markdown.

    Снимает markdown-разметку (ссылки, картинки, маркер цитаты ``> ``),
    но не теряет содержимое цитат — оно остаётся в тексте. Отдельная от
    `plain_text` функция, чтобы вызывающий (`parse_thread`) разбирал HTML
    поста один раз, а не дважды: `markdown` теперь хранится в базе сам по
    себе (тело заметки), `text` — производная от него (поиск, сверка цитат).
    """
    # URL может содержать один уровень вложенных скобок (напр. "page(1).html") —
    # наивный "до первой ')'" разбор обрезает адрес и оставляет хвост как текст.
    _paren_url = r"(?:[^()]|\([^()]*\))*"
    md = re.sub(r"!\[\]\(" + _paren_url + r"\)", "", md)
    md = re.sub(r"\[([^\]]*)\]\(" + _paren_url + r"\)", r"\1", md)
    # Вложенная цитата (ответ на цитату внутри чужой цитаты) даёт в to_markdown
    # несколько уровней "> " подряд — снимаем все, а не один.
    md = re.sub(r"^(> )+", "", md, flags=re.M)
    return re.sub(r"[ \t]{2,}", " ", md).strip()


def plain_text(html: str) -> str:
    """Плоский текст прямо из HTML — тонкая обёртка над двумя шагами."""
    return plain_text_from_markdown(to_markdown(html))
