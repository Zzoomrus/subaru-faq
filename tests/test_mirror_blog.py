import json
from pathlib import Path

import yaml

from pipeline import db, mirror_blog

FIX_ASSETS = Path(__file__).parent / "fixtures" / "faq_assets"


def _frontmatter(md: str) -> dict:
    lines = md.split("\n")
    assert lines[0] == "---"
    end = next(i for i in range(1, len(lines)) if lines[i] == "---")
    return yaml.safe_load("\n".join(lines[1:end]))


def _insert_post(conn, blog, post_id, title, author, posted_at, body_md, tags,
                  source_url, snapshot_ts, is_excerpt=0, truncated=0):
    conn.execute(
        "INSERT INTO blog_posts(blog, post_id, title, author, posted_at, body_md, tags, "
        "source_url, snapshot_ts, is_excerpt, truncated) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (blog, post_id, title, author, posted_at, body_md, json.dumps(tags, ensure_ascii=False),
         source_url, snapshot_ts, is_excerpt, truncated))


def _seed(tmp_path, name="t.sqlite"):
    conn = db.connect(tmp_path / name)
    db.init_schema(conn)
    _insert_post(conn, "a-detal", 304, "Удобство заказа автозапчастей", "Иван",
                 "15.09.2014 09:59:26",
                 "Текст записи с картинкой ![](http://subaru-faq.ru/upload/blog/84b/x.jpg) внутри.",
                 ["запчасти"],
                 "http://www.subaru-faq.ru/blogs/index.php?page=post&blog=a-detal&post_id=304",
                 "20140915095926")
    conn.execute(
        "INSERT INTO blog_images(blog, post_id, url, local_path) VALUES "
        "('a-detal', 304, 'http://subaru-faq.ru/upload/blog/84b/x.jpg', NULL)")
    conn.execute(
        "INSERT INTO blog_comments(blog, post_id, comment_id, parent_id, depth, author, posted_at, text_md) "
        "VALUES ('a-detal', 304, 640, NULL, 0, 'scilla', '11.08.2011 10:38:01', 'Первый комментарий.')")
    conn.execute(
        "INSERT INTO blog_comments(blog, post_id, comment_id, parent_id, depth, author, posted_at, text_md) "
        "VALUES ('a-detal', 304, 641, 640, 1, 'Игорь', '11.08.2011 12:33:37', 'Ответ на первый.')")

    _insert_post(conn, "remont", 184, "Замена масла", "Пётр", "01.01.2015 10:00:00",
                 "Ответ с ![](http://subaru-faq.ru/upload/blog/dead/gone.jpg) утраченной картинкой.",
                 [], "http://www.subaru-faq.ru/blogs/index.php?page=post&blog=remont&post_id=184",
                 "20150101100000")
    conn.execute(
        "INSERT INTO blog_images(blog, post_id, url, local_path) VALUES "
        "('remont', 184, 'http://subaru-faq.ru/upload/blog/dead/gone.jpg', NULL)")
    # Коллизия номера с другим блогом (найдено разведкой задачи 7) — тот же
    # post_id=184, другой блог, ДРУГАЯ запись.
    _insert_post(conn, "remontSubaru", 184, "Другая запись под тем же номером", "Пётр",
                 "02.02.2016 11:00:00", "Совсем другой текст.", [],
                 "http://www.subaru-faq.ru/blogs/index.php?page=post&blog=remontSubaru&post_id=184",
                 "20160202110000")

    _insert_post(conn, "infinite_branch", 81, "Дешевые путевки", "Xena", "10.10.2010 10:00:00",
                 "Полный текст выдержки целиком.", [],
                 "http://subaru-faq.ru/blogs/index.php?page=history&PAGEN_1=4",
                 "20101010100000", is_excerpt=1, truncated=0)
    _insert_post(conn, "autofxz", 148, "Обрезанная запись", "Автор", "05.05.2015 05:00:00",
                 "Начало текста, которое обрывается.", [],
                 "http://www.subaru-faq.ru/blogs/index.php?page=blog&blog=autofxz",
                 "20150505050000", is_excerpt=1, truncated=1)

    # Смайл движка внутри тела — chrome, должен молча исчезнуть при рендере
    # (attachments.classify), а не превратиться в пометку об утрате.
    _insert_post(conn, "-Help-", 999, "Со смайлом", "Игорь", "01.01.2011 00:00:00",
                 "Спасибо! ![](http://subaru-faq.ru/bitrix/images/blog/smile/icon_smile.gif) Пожалуйста.",
                 [], "http://subaru-faq.ru/blogs/index.php?page=post&blog=-Help-&post_id=999",
                 "20110101000000")

    conn.commit()
    return conn


def test_full_record_frontmatter_and_body(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "Блоги"
    mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    md = (out / "Блог a-detal 304.md").read_text(encoding="utf-8")
    fm = _frontmatter(md)
    assert fm["номер"] == 304
    assert fm["блог"] == "a-detal"
    assert fm["автор"] == "Иван"
    assert fm["дата"] == "15.09.2014 09:59:26"
    assert fm["адрес"] == "http://www.subaru-faq.ru/blogs/index.php?page=post&blog=a-detal&post_id=304"
    assert fm["снимок"] == "20140915095926"
    assert fm["теги"] == ["запчасти"]
    assert fm["выдержка"] is False
    assert fm["aliases"] == ["Удобство заказа автозапчастей"]
    assert "# Удобство заказа автозапчастей" in md
    assert "[!warning]" not in md


def test_image_found_and_embedded(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "Блоги"
    mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    md = (out / "Блог a-detal 304.md").read_text(encoding="utf-8")
    assert "![[" in md
    assert "не сохранилось" not in md


def test_missing_image_gets_honest_loss_note(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "Блоги"
    mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    md = (out / "Блог remont 184.md").read_text(encoding="utf-8")
    assert "изображение не сохранилось" in md
    assert "![[" not in md


def test_chrome_smiley_vanishes_without_broken_embed_or_loss_note(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "Блоги"
    mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    md = (out / "Блог -Help- 999.md").read_text(encoding="utf-8")
    assert "![[" not in md
    assert "не сохранилось" not in md
    assert "smile" not in md
    assert "Спасибо!" in md and "Пожалуйста." in md


def test_same_post_id_in_different_blogs_gets_separate_notes(tmp_path):
    # Разведка задачи 7: post_id уникален только внутри блога (10 коллизий
    # remont/remontSubaru на живом корпусе) — имя заметки обязано включать
    # слаг блога, иначе вторая запись затёрла бы первую.
    conn = _seed(tmp_path)
    out = tmp_path / "Блоги"
    mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    assert (out / "Блог remont 184.md").exists()
    assert (out / "Блог remontSubaru 184.md").exists()
    a = (out / "Блог remont 184.md").read_text(encoding="utf-8")
    b = (out / "Блог remontSubaru 184.md").read_text(encoding="utf-8")
    assert a != b
    assert "Другая запись" in b and "Другая запись" not in a


def test_excerpt_gets_warning_callout(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "Блоги"
    mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    md = (out / "Блог infinite_branch 81.md").read_text(encoding="utf-8")
    fm = _frontmatter(md)
    assert fm["выдержка"] is True
    assert "[!warning] Запись не сохранилась отдельной страницей" in md
    assert "обрезан" not in md


def test_truncated_excerpt_gets_extra_warning_line(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "Блоги"
    mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    md = (out / "Блог autofxz 148.md").read_text(encoding="utf-8")
    assert "обрезан" in md


def test_comments_rendered_with_predictable_anchors_and_parent_note(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "Блоги"
    mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    md = (out / "Блог a-detal 304.md").read_text(encoding="utf-8")
    assert "## Комментарии" in md
    assert "##### Комментарий 640" in md
    assert "##### Комментарий 641" in md
    assert "Первый комментарий." in md
    assert "Ответ на первый." in md
    assert "(ответ на комментарий №640)" in md
    # Комментарий верхнего уровня не должен получить пометку "ответ на".
    top_section = md.split("##### Комментарий 640")[1].split("##### Комментарий 641")[0]
    assert "ответ на комментарий" not in top_section


def test_record_without_comments_has_no_comments_section(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "Блоги"
    mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    md = (out / "Блог remont 184.md").read_text(encoding="utf-8")
    assert "## Комментарии" not in md


def test_write_all_removes_stale_notes_but_not_foreign_files(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "Блоги"
    out.mkdir(parents=True)
    (out / "Блог устаревший 1.md").write_text("устаревшая", encoding="utf-8")
    (out / "не наша заметка.md").write_text("чужой файл", encoding="utf-8")
    n = mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                               assets_root=FIX_ASSETS / "assets")
    assert n == 6
    assert not (out / "Блог устаревший 1.md").exists()
    assert (out / "не наша заметка.md").exists()


def test_comment_images_are_rendered_not_marked_lost(tmp_path):
    # M1 итогового ревью Ф2: `_render_comments` звал `render_post_body` с
    # ПУСТЫМ словарём картинок, поэтому любая картинка в комментарии
    # становилась пометкой «не сохранилось» даже когда файл лежал в архиве
    # Ф0/Ф1. Теперь словарь один на запись и её комментарии.
    conn = db.connect(tmp_path / "c.sqlite")
    db.init_schema(conn)
    _insert_post(conn, "remont", 900, "Запись с комментариями", "Пётр", "01.01.2015 10:00:00",
                  "Тело без картинок.", [],
                  "http://www.subaru-faq.ru/blogs/index.php?page=post&blog=remont&post_id=900",
                  "20150101100000")
    have = "http://subaru-faq.ru/upload/blog/84b/x.jpg"
    gone = "http://subaru-faq.ru/upload/blog/dead/gone.jpg"
    conn.execute("INSERT INTO blog_comments(blog, post_id, comment_id, parent_id, depth, author, "
                 "posted_at, text_md) VALUES ('remont', 900, 5, NULL, 0, 'scilla', "
                 "'11.08.2011 10:38:01', 'смотри ![](%s) и ![](%s)')" % (have, gone))
    conn.execute("INSERT INTO blog_images(blog, post_id, comment_id, url, local_path) "
                 "VALUES ('remont', 900, 5, ?, NULL)", (have,))
    conn.execute("INSERT INTO blog_images(blog, post_id, comment_id, url, local_path) "
                 "VALUES ('remont', 900, 5, ?, NULL)", (gone,))
    conn.commit()

    out = tmp_path / "Блоги"
    mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    md = (out / "Блог remont 900.md").read_text(encoding="utf-8")
    assert "![[assets/" in md                              # найденная картинка вставлена
    assert "изображение не сохранилось: %s" % gone in md    # утраченная — честная пометка
    assert "изображение не сохранилось: %s" % have not in md


def test_parser_collects_comment_image_urls_and_skips_engine_smileys():
    """Вторая половина M1: адреса картинок комментариев вообще не писались в
    базу, то есть будущий добор их бы не нашёл.

    Реальная страница корпуса, в комментарий которой добавлены две картинки:
    содержательная и смайл движка. В самом корпусе комментариев С картинками
    среди сохранившихся страниц нет ни одного (все 16 пометок об утрате
    пришли из тел записей), поэтому вставка в разметку — единственный
    способ проверить путь на настоящем HTML, а не на синтетике целиком.
    """
    from pipeline import parse_blog
    html = (Path(__file__).parent / "fixtures" / "blog_post_with_comments.html").read_bytes().decode(
        "cp1251", "replace")
    marker = '<div class="blog-comment-content">'
    assert html.count(marker) >= 1
    injected = html.replace(
        marker,
        marker + '<img src="/upload/blog/84b/x.jpg" />'
                 '<img src="/bitrix/images/blog/smile/smile.gif" />', 1)
    post = parse_blog.parse_post(injected, "http://www.subaru-faq.ru/blogs/index.php?page=post&"
                                            "blog=remont&post_id=184")
    assert post is not None
    with_images = [c for c in post.comments if c.images]
    assert len(with_images) == 1
    # Абсолютный адрес — как у картинок записи; смайл движка отфильтрован тем
    # же правилом `attachments.classify`, что у форума и FAQ.
    assert with_images[0].images == ["http://subaru-faq.ru/upload/blog/84b/x.jpg"]
    # Смайл остаётся в `text_md` и вырезается ПОЗЖЕ, на рендере заметки
    # (`mirror.render_post_body` по тому же правилу) — намеренное решение
    # задачи 7, см. докстринг `parse_blog`: на этапе разбора текст не
    # редактируется.
    assert with_images[0].text_md.count("![](") == 2
    assert "bitrix/images/blog/smile" in with_images[0].text_md


def test_entry_images_do_not_leak_into_comments(tmp_path):
    """Первая попытка исправить M1 была неверной, и вот её след.

    `mirror.render_post_body` выводит адреса из словаря, не встретившиеся в
    тексте, отдельным блоком в КОНЕЦ тела (осознанный фолбэк задачи 4 против
    молчаливой потери пометки). Поэтому общий словарь картинок на всю запись
    дал каждому комментарию хвост из чужих картинок: на боевом корпусе
    +1316 ложных вставок в 49 заметках. Словарь обязан быть по области
    видимости — этот тест ловит возврат к общему.
    """
    conn = db.connect(tmp_path / "leak.sqlite")
    db.init_schema(conn)
    _insert_post(conn, "remont", 901, "Запись с картинкой", "Пётр", "01.01.2015 10:00:00",
                  "Тело с ![](http://subaru-faq.ru/upload/blog/84b/x.jpg) картинкой.", [],
                  "http://www.subaru-faq.ru/blogs/index.php?page=post&blog=remont&post_id=901",
                  "20150101100000")
    conn.execute("INSERT INTO blog_images(blog, post_id, comment_id, url, local_path) "
                 "VALUES ('remont', 901, NULL, 'http://subaru-faq.ru/upload/blog/84b/x.jpg', NULL)")
    conn.execute("INSERT INTO blog_comments(blog, post_id, comment_id, parent_id, depth, author, "
                 "posted_at, text_md) VALUES ('remont', 901, 7, NULL, 0, 'scilla', "
                 "'11.08.2011 10:38:01', 'комментарий вообще без картинок')")
    conn.commit()

    out = tmp_path / "Блоги"
    mirror_blog.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    md = (out / "Блог remont 901.md").read_text(encoding="utf-8")
    body, comments = md.split("## Комментарии", 1)
    assert "![[assets/" in body            # картинка записи на своём месте в теле
    assert "![[assets/" not in comments    # и её нет в комментарии, где её не было
    assert "изображение не сохранилось" not in comments
