"""Генератор зеркала блогов: заметка на каждую запись `blog_posts` (Ф2,
задача 7).

Формат следует `pipeline.mirror_faq` там, где применимо, и переиспользует
код форума/FAQ напрямую (тот же прецедент, что и там — `mirror_faq`
переиспользует `mirror`, здесь то же самое разрешение уже дал лид):

- тело записи и текст каждого комментария идут через `mirror.
  render_post_body` — картинки на своё место, честная пометка об утрате,
  СМАЙЛЫ ДВИЖКА (`bitrix/images/blog/smile/...`) молча вырезаются тем же
  правилом `attachments.classify`, что и у форума/FAQ (см. `pipeline.
  parse_blog`, докстринг про то, что смайлы намеренно НЕ отфильтрованы на
  этапе разбора — только на этапе рендера заметки, здесь);
- YAML-экранирование фронтматтера — `mirror._yaml_dquote`;
- экранирование `[[`/заголовков внутри текста — `mirror._escape_wikilink_
  open`/`mirror._escape_headings` (тот же риск, что у поста форума и
  ответа FAQ: случайный `#`/`[[` в авторском тексте не должен сломать
  структуру заметки или адрес следующей секции).

Имя заметки — `Блог <blog> <post_id>.md`, НЕ просто `Блог <post_id>.md`,
как буквально просил бриф: разведка задачи 7 нашла, что `post_id`
уникален только ВНУТРИ одного блога — на живом корпусе 10 номеров
пересекаются между блогами `remont`/`remontSubaru` (тот же класс
находки, что и `(engine, nr)` у FAQ в задаче 6, см. `parse_blog.py`).
Слаг блога всегда безопасен для имени файла (проверено на всех 159
блогах корпуса — ни пробелов, ни спецсимволов файловой системы).

Заголовки внутри заметки — предсказуемый, одинаковый у всех записей
паттерн для будущих сносок: `# <название>` (H1, как у форума и FAQ),
`## Запись` (сам текст), `## Комментарии` (если они есть) и
`##### Комментарий <ID>` на каждый комментарий —
`[[Блог <blog> <post_id>#Комментарий <ID>]]` адресует один комментарий
до следующего заголовка того же уровня, так же как `[[Тема N#Пост MID]]`
у форума. Адрес тела — `[[Блог <blog> <post_id>#Запись]]`, и это не
косметика: H1 из названия адресом быть не может (названия не уникальны —
одно встречается в трёх заметках корпуса). Полный список обещанных
адресов проверяется тестом `tests/test_anchor_contract.py` и описан для
человека в `docs/контракт-зеркала.md`.

Картинки — та же схема, что у FAQ: `blog_images.url` ищется среди уже
скачанных вложений форума Ф0/Ф1 (`data/raw/archive/manifest-assets.jsonl`
+ `.../assets`) — те же файлы на том же хосте (`upload/blog/...`),
добытые раньше по другому поводу; сеть в задаче 7 не трогали. Помощники
поиска (`_load_asset_index`/`_resolve_image`/...) не копируются, а
импортируются из `pipeline.mirror_faq` — они не специфичны для FAQ,
только имя модуля унаследовано от того, где появились первыми.
"""
import json
import re
from pathlib import Path

from pipeline import mirror, mirror_faq

DEFAULT_ASSETS_MANIFEST = mirror_faq.DEFAULT_ASSETS_MANIFEST
DEFAULT_ASSETS_ROOT = mirror_faq.DEFAULT_ASSETS_ROOT

_NOTE_NAME = re.compile(r"^Блог (.+) (\d+)\.md$")


def _filename(blog: str, post_id: int) -> str:
    return "Блог %s %d.md" % (blog, post_id)


def _render_comments(conn, blog: str, post_id: int) -> str:
    rows = conn.execute(
        "SELECT comment_id, parent_id, author, posted_at, text_md FROM blog_comments "
        "WHERE blog = ? AND post_id = ? ORDER BY comment_id", (blog, post_id)).fetchall()
    if not rows:
        return ""
    out = ["## Комментарии", ""]
    for comment_id, parent_id, author, posted_at, text_md in rows:
        out.append("##### Комментарий %d" % comment_id)
        out.append("")
        meta = " · ".join(x for x in (author or "аноним", posted_at or "") if x)
        out.append("*%s*" % meta)
        if parent_id is not None:
            out.append("*(ответ на комментарий №%d)*" % parent_id)
        out.append("")
        body = mirror.render_post_body(text_md or "", {})
        out.append(body if body else "(пусто)")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def render_entry(row: tuple, images_by_url: dict, comments_md: str) -> str:
    (blog, post_id, title, author, posted_at, body_md, tags_json,
     source_url, snapshot_ts, is_excerpt, truncated) = row
    title = title or ""
    tags = json.loads(tags_json) if tags_json else []

    body = mirror.render_post_body(body_md or "", images_by_url)
    title_line = mirror._escape_headings(mirror._escape_wikilink_open(title))

    out = ["---",
           "номер: %d" % post_id,
           "блог: %s" % mirror._yaml_dquote(blog),
           "автор: %s" % mirror._yaml_dquote(author or ""),
           "дата: %s" % mirror._yaml_dquote(posted_at or ""),
           "адрес: %s" % mirror._yaml_dquote(source_url or ""),
           "снимок: %s" % mirror._yaml_dquote(snapshot_ts or ""),
           "теги: [%s]" % ", ".join(mirror._yaml_dquote(t) for t in tags),
           "выдержка: %s" % ("true" if is_excerpt else "false"),
           "aliases: [%s]" % mirror._yaml_dquote(title),
           "---", ""]

    if is_excerpt:
        out.append("> [!warning] Запись не сохранилась отдельной страницей — восстановлено по выдержке из ленты")
        if truncated:
            out.append("> Текст мог быть обрезан лентой (\"Читать подробнее...\") — это не вся запись.")
        out.append("")

    out.append("# %s" % (title_line or "Блог %d" % post_id))
    out.append("")
    # `## Запись` — АДРЕС тела записи для сносок статей (`[[Блог <blog>
    # <post_id>#Запись]]`), а не украшение. До правки по дефекту C2
    # итогового ревью Ф2 докстринг модуля обещал этот заголовок, а код
    # выводил только H1 из названия — то есть единственным доступным
    # адресом тела было само название, и оно НЕ уникально (`# была у меня
    # импреза 99г.в RS` встречается в трёх заметках корпуса) и меняется при
    # любом пере-разборе страницы. Ровно от этой нестабильности ушло
    # форумное зеркало, выбрав `##### Пост <MID>` вместо «автор · дата»
    # (см. докстринг `pipeline.mirror`). Убрать заголовок нельзя, не сломав
    # все сноски на тела записей; тест-контракт на это — `tests/
    # test_anchor_contract.py`.
    out.append("## Запись")
    out.append("")
    out.append(body if body else "(текст не сохранился)")
    out.append("")
    if comments_md:
        out.append(comments_md)
    return "\n".join(out).rstrip("\n") + "\n"


def write_all(conn, out_dir: Path, assets_manifest: Path = DEFAULT_ASSETS_MANIFEST,
              assets_root: Path = DEFAULT_ASSETS_ROOT) -> int:
    """Пишет заметку на каждую запись `blog_posts` и убирает заметки
    исчезнувших. Тот же предохранитель, что у `mirror.write_all`/`mirror_
    faq.write_all` (удалений не может быть больше, чем записанных заметок).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = out_dir / "assets"
    asset_index = mirror_faq._load_asset_index(assets_manifest)

    names: set[str] = set()
    used_assets: set[str] = set()
    n = 0
    rows = conn.execute(
        "SELECT blog, post_id, title, author, posted_at, body_md, tags, source_url, "
        "snapshot_ts, is_excerpt, truncated FROM blog_posts ORDER BY blog, post_id").fetchall()
    for row in rows:
        blog, post_id = row[0], row[1]
        images_by_url = {}
        for (url,) in conn.execute(
                "SELECT url FROM blog_images WHERE blog = ? AND post_id = ?", (blog, post_id)):
            local = mirror_faq._resolve_image(url, asset_index, assets_root, assets_dir)
            if local:
                used_assets.add(local.rsplit("/", 1)[-1])
            images_by_url[url] = {"local_path": local}
        comments_md = _render_comments(conn, blog, post_id)
        name = _filename(blog, post_id)
        (out_dir / name).write_text(render_entry(row, images_by_url, comments_md), encoding="utf-8")
        names.add(name)
        n += 1

    stale = [p for p in sorted(out_dir.glob("Блог *.md")) if _NOTE_NAME.match(p.name) and p.name not in names]
    if len(stale) > n:
        raise RuntimeError(
            "отказ убирать заметки блогов: записано %d, под удаление попало %d. "
            "Похоже, база не описывает это зеркало. Зеркало не тронуто: %s"
            % (n, len(stale), out_dir))
    for path in stale:
        path.unlink()
    mirror.prune_assets(assets_dir, used_assets, n)
    return n
