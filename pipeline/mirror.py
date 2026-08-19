"""Генератор зеркала: заметка Markdown на каждую тему форума.

Формат заметки и решения зафиксированы в `.superpowers/sdd/2026-08-19-.../task-7-brief.md`
и в шести дополняющих его решениях (см. отчёт задачи 7). Кратко:

- Имя файла — `Тема <TID>.md`, без названия темы (переименование сломало бы
  сноски); название — только в `aliases`.
- Якорь поста `^p<MID>` клеится к КОНЦУ ТЕКСТА поста, а не к концу всего
  блока: у поста с потерянной картинкой блок кончается коллаутом, и якорь
  внутри цитаты раскрывал бы пометку вместо текста — а весь смысл блочной
  ссылки в том, чтобы раскрывался именно текст.
- Интерфейсный хром форума (смайлы `images/smiley_icons`, иконки
  `bitrix/images`, `bitrix/components`) не рендерится вовсе — не вставка,
  не пометка об утрате: терять там нечего, это не контент поста.
- Всё остальное без файла — коллаут "изображение не сохранилось" с
  исходным URL. Вставка `![[...]]` происходит только когда `local_path`
  не пуст, независимо от значения `status` (в базе есть мусорная запись
  status='ok' с пустым local_path).
- Темы без единого поста получают заметку с метаданными оглавления и
  коллаутом "содержимое не сохранилось".
- `replies_expected IS NULL` -> "неизвестно" во frontmatter, не 0 и не пусто.
"""
from pathlib import Path

# Интерфейсный хром форума: смайлы и иконки, вшитые в шаблон движка.
# На корпусе это 20501 из 20764 "local"-вложений (см. отчёт задачи 7) —
# у них никогда не было и не будет собственного файла, это не потеря контента.
_CHROME_MARKERS = ("bitrix/images", "images/smiley_icons", "bitrix/components")


def _is_interface_chrome(kind: str, url: str) -> bool:
    if kind != "local":
        return False
    url = url or ""
    return any(marker in url for marker in _CHROME_MARKERS)


def _ru_dt(iso: str) -> str:
    if not iso or len(iso) < 10:
        return iso or ""
    d, _, t = iso.partition(" ")
    y, m, day = d.split("-")
    return "%s.%s.%s%s" % (day, m, y, (" " + t) if t else "")


def _yaml_str(s: str) -> str:
    return (s or "").replace('"', "'")


def render_thread(conn, tid: int) -> str:
    row = conn.execute(
        "SELECT t.tid, t.fid, t.title, t.author, t.started_at, t.replies_expected, t.views, "
        "COALESCE(s.title, '') FROM threads t LEFT JOIN sections s ON s.fid = t.fid WHERE t.tid = ?",
        (tid,)).fetchone()
    if row is None:
        raise KeyError(tid)
    tid, fid, title, author, started, replies, views, section = row

    replies_str = "неизвестно" if replies is None else str(replies)
    out = ["---",
           "tid: %d" % tid,
           "fid: %d" % fid,
           "раздел: %s" % _yaml_str(section),
           'aliases: ["%s"]' % _yaml_str(title or "Тема %d" % tid),
           "автор: %s" % _yaml_str(author or ""),
           "начата: %s" % (started or ""),
           "ответов: %s" % replies_str,
           "просмотров: %s" % (views if views is not None else ""),
           "---", "", "# %s" % (title or "Тема %d" % tid), ""]

    posts = conn.execute(
        "SELECT mid, author, posted_at, number, text FROM posts WHERE tid = ? ORDER BY page_no, mid",
        (tid,)).fetchall()

    if not posts:
        out.append("> [!missing] содержимое не сохранилось")
        out.append("")
        return "\n".join(out)

    for mid, p_author, posted_at, number, text in posts:
        out.append("##### %s · %s%s" % (p_author or "аноним", _ru_dt(posted_at or ""),
                                         (" · " + number) if number else ""))
        out.append("")

        body_text = (text or "").rstrip()
        # Решение 1: якорь клеится к тексту поста, а не к концу всего блока —
        # ниже него могут пойти картинки/коллауты, которые не должны
        # оказаться "внутри" сноски на пост.
        if body_text:
            out.append("%s ^p%d" % (body_text, mid))
        else:
            out.append("^p%d" % mid)

        extra_blocks = []
        for a_kind, a_url, a_local, a_status in conn.execute(
                "SELECT kind, url, local_path, status FROM attachments WHERE mid = ?", (mid,)):
            if _is_interface_chrome(a_kind, a_url):
                continue
            if a_local:
                # Решение 4: вставка файла только когда local_path реально
                # заполнен — status='ok' сам по себе ничего не гарантирует.
                extra_blocks.append("![[%s]]" % a_local)
            else:
                extra_blocks.append("> [!missing] изображение не сохранилось\n> %s" % (a_url or ""))

        for block in extra_blocks:
            out.append("")
            out.append(block)

        out.append("")

    return "\n".join(out)


def write_all(conn, out_dir: Path) -> int:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for (tid,) in conn.execute("SELECT tid FROM threads ORDER BY tid"):
        (out_dir / ("Тема %d.md" % tid)).write_text(render_thread(conn, tid), encoding="utf-8")
        n += 1
    return n
