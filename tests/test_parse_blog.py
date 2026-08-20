from pathlib import Path

from pipeline import parse_blog

FIX = Path(__file__).parent / "fixtures"


def _html(name: str) -> str:
    return (FIX / name).read_bytes().decode("cp1251", "replace")


def test_parses_simple_post_without_tags_or_comments():
    p = parse_blog.parse_post(
        _html("blog_post_simple.html"),
        "http://www.subaru-faq.ru:80/blogs/index.php?page=post&blog=a-detal&post_id=304")
    assert p is not None
    assert p.blog == "a-detal"
    assert p.post_id == 304
    assert p.title == "Удобство заказа автозапчастей через интернет"
    assert p.author == "Иван"
    assert p.posted_at == "15.09.2014 09:59:26"
    assert p.tags == []
    assert p.comments == []
    assert p.images == []
    assert not p.is_excerpt
    assert "Рынок автозапчастей широк" in p.body_md


def test_tags_found_even_when_broken_markup_pushes_meta_outside_the_block():
    # Разведка задачи 7: незакрытый `<table>` где-то в теле (WYSIWYG-мусор)
    # заставляет lxml закрыть `div.blog-post` раньше положенного, и
    # `div.blog-post-meta`/`div.blog-post-tag` (в вёрстке идут СЛЕДОМ за
    # `blog-post-content`) оказываются формально вне блока записи — на живом
    # корпусе так у 308/488 полных записей. `parse_post` ищет теги/счётчик
    # комментариев по всему документу, а не внутри блока, — именно поэтому.
    p = parse_blog.parse_post(
        _html("blog_post_with_tags.html"),
        "http://www.subaru-faq.ru:80/blogs/index.php?page=post&blog=aksanova_taisiya&post_id=5892")
    assert p is not None
    assert p.tags == ["серьги"]
    assert p.declared_comments == 0
    # Побочный мусор вёрстки (висячий "</table>" WYSIWYG-редактора) не
    # должен просочиться в тело заметки как текст.
    assert "</table>" not in p.body_md
    assert "MyGold24" in p.body_md


def test_avatar_image_is_stripped_but_real_content_images_survive():
    # Djedaj/73 — пост из одних фотографий (get_text() после снятия аватара
    # был бы пуст, но markdown — нет, картинки остаются картинками):
    # аватарка автора (`/upload/blog/avatar/...`) должна исчезнуть целиком
    # (не оставить даже пометку об утрате — decorативная, не контент), а
    # шесть настоящих фотографий с photofile.ru — остаться.
    p = parse_blog.parse_post(
        _html("blog_post_photo_only.html"),
        "http://subaru-faq.ru/blogs/index.php?page=post&blog=Djedaj&post_id=73")
    assert p is not None
    assert p.body_md.strip() != ""
    assert "avatar" not in p.body_md
    assert len(p.images) == 6
    assert all(u.startswith("http://photofile.ru/") for u in p.images)


def test_comments_parsed_with_thread_depth_and_parent():
    p = parse_blog.parse_post(
        _html("blog_post_with_comments.html"),
        "http://subaru-faq.ru/blogs/index.php?page=post&blog=-Help-&post_id=151&commentId=668")
    assert p is not None
    assert p.declared_comments == 19
    assert len(p.comments) == 19
    first = p.comments[0]
    assert first.comment_id == 640
    assert first.parent_id is None
    assert first.depth == 0
    assert first.author == "scilla"
    assert first.posted_at == "11.08.2011 10:38:01"
    assert "Когда угнали" in first.text_md

    second = p.comments[1]
    assert second.comment_id == 641
    assert second.parent_id == 640
    assert second.depth == 1

    # Комментарий с "Ответить"/"Ссылка"/"Родитель" в конце — служебные ссылки
    # не должны просочиться в текст.
    assert "Ответить" not in first.text_md
    assert "Ссылка" not in first.text_md


def test_merge_paginated_prefers_canonical_page_and_unions_comments():
    p1 = parse_blog.parse_post(
        _html("blog_pagen_page1.html"),
        "http://www.subaru-faq.ru/blogs/index.php?page=post&blog=B10&post_id=236")
    p2 = parse_blog.parse_post(
        _html("blog_pagen_page2.html"),
        "http://subaru-faq.ru/blogs/index.php?pagen=2&page=post&blog=B10&post_id=236")
    assert p1 is not None and p2 is not None
    assert len(p1.comments) == 3
    assert len(p2.comments) == 12

    merged = parse_blog.merge_paginated([p2, p1])  # порядок не важен
    assert merged.blog == "B10"
    assert merged.post_id == 236
    # Заголовок/адрес — с канонической страницы (без `pagen`).
    assert merged.source_url == "http://www.subaru-faq.ru/blogs/index.php?page=post&blog=B10&post_id=236"
    # Комментарии — объединение, отсортированное по id.
    ids = [c.comment_id for c in merged.comments]
    assert ids == sorted(ids)
    assert set(ids) == {c.comment_id for c in p1.comments} | {c.comment_id for c in p2.comments}
    assert len(merged.comments) == 15


def test_listing_excerpts_extracted_with_post_id_from_link():
    items = parse_blog.parse_listing_excerpts(
        _html("blog_listing_small.html"),
        "http://subaru-faq.ru/blogs/index.php?page=history&PAGEN_1=4")
    assert len(items) == 2
    keys = {(i.blog, i.post_id) for i in items}
    assert keys == {("infinite_branch", 81), ("infinite_branch", 43)}
    for i in items:
        assert i.is_excerpt
        assert i.comments == []
        assert i.title


def test_listing_excerpt_detects_truncation_marker():
    items = parse_blog.parse_listing_excerpts(
        _html("blog_listing_truncated.html"),
        "http://www.subaru-faq.ru:80/blogs/index.php?page=blog&blog=autofxz")
    target = next(i for i in items if i.post_id == 148)
    assert target.blog == "autofxz"
    assert target.truncated is True
    # Сама метка "Читать подробнее..." — служебная ссылка, не текст записи.
    assert "Читать подробнее" not in target.body_md


def test_span_title_page_yields_no_excerpts():
    # Полная запись (заголовок-`<span>`) не должна попасть в разбор ленты,
    # даже если её случайно передать в `parse_listing_excerpts`.
    items = parse_blog.parse_listing_excerpts(
        _html("blog_post_simple.html"),
        "http://www.subaru-faq.ru:80/blogs/index.php?page=post&blog=a-detal&post_id=304")
    assert items == []


def test_unrelated_page_yields_no_post():
    url = "http://subaru-faq.ru/blogs/index.php?page=post&blog=x&post_id=1"
    assert parse_blog.parse_post(_html("broken_db_error.html"), url) is None


def test_post_url_without_post_id_yields_none():
    assert parse_blog.parse_post(_html("blog_post_simple.html"), "http://subaru-faq.ru/blogs/index.php?page=post") is None
