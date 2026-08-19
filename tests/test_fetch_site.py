"""Тесты добора FAQ и блогов (задача 5, план Ф2 «Добор»).

--- Дословно из брифа (task-5-brief.md, Шаг 1) --------------------------
"Тест на построение плана из ответа CDX (замокать fetcher.cdx_snapshots,
проверить, что служебные адреса — mode=write, login, register, search —
отсеиваются, а записи FAQ остаются)." Ниже это выполнено буквально
(test_build_list_drops_brief_example_service_urls) — но брифовые примеры
("mode=write", "login", "register") гипотетические, а не то, что реально
нашлось в CDX под префиксом /faq/ (там их нет вовсе — см. отчёт задачи 5,
"Отсев служебных адресов": /login,/register,/search живут под /auth/ и
/search/, за пределами префикса faq/blogs). Реальный мусор — другой
(action=ADD2BASKET/BUY, print/sphrase_id-дубли, gfx-иконки для FAQ;
page=search/rss/user/group/blog_edit для блогов) — и проверяется отдельными
тестами ниже на данных, снятых с боевого CDX 20.08.2026.
"""
import json
import urllib.parse
from pathlib import Path

from pipeline import assets_state, fetch_site, fetcher

FIX = Path(__file__).parent / "fixtures"


def _row(url, ts="20100101000000"):
    return (ts, url)


# --- build_list: фильтр служебных адресов + дедуп по нормализованному URL ---

def test_build_list_drops_brief_example_service_urls(monkeypatch):
    # Буквально из брифа: login/register/search/mode=write должны быть
    # отсеяны, а обычная запись FAQ — остаться.
    rows = [
        _row("http://subaru-faq.ru/faq/auth.php?login=yes"),
        _row("http://subaru-faq.ru/faq/auth.php?register=yes"),
        _row("http://subaru-faq.ru/faq/search.php?q=x"),
        _row("http://subaru-faq.ru/faq/faq.php?mode=write&nr=1"),
        _row("http://subaru-faq.ru/faq/faq.php?display=faq&nr=11&catnr=1&prog=COMMON&lang=ru"),
    ]
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", lambda url, **kw: rows)
    plan = fetch_site.build_list("faq")
    urls = [item["url"] for item in plan]
    assert urls == ["http://subaru-faq.ru/faq/faq.php?display=faq&nr=11&catnr=1&prog=COMMON&lang=ru"]


def test_build_list_faq_drops_static_assets(monkeypatch):
    # Реальная находка на CDX (20.08.2026, префикс subaru-faq.ru/faq/): 6 из
    # 557 адресов — статика раздела (css, иконки в gfx/), не HTML-страницы.
    rows = [
        _row("http://www.subaru-faq.ru/faq/faq.css"),
        _row("http://www.subaru-faq.ru/faq/gfx/comment.gif"),
        _row("http://www.subaru-faq.ru/faq/gfx/ratings/2half.gif"),
        _row("http://www.subaru-faq.ru/faq/index.php?ELEMENT_ID=10"),
    ]
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", lambda url, **kw: rows)
    plan = fetch_site.build_list("faq")
    urls = [item["url"] for item in plan]
    assert urls == ["http://www.subaru-faq.ru/faq/index.php?ELEMENT_ID=10"]


def test_build_list_faq_drops_basket_actions(monkeypatch):
    # Реальная находка: 8 из 557 — экшены каталога Bitrix (ADD2BASKET/BUY),
    # не FAQ-контент вовсе.
    rows = [
        _row("http://www.subaru-faq.ru:80/faq/index.php?ELEMENT_ID=108&action=ADD2BASKET&id="),
        _row("http://www.subaru-faq.ru:80/faq/index.php?ELEMENT_ID=108&action=BUY&id="),
        _row("http://www.subaru-faq.ru:80/faq/index.php?ELEMENT_ID=108"),
    ]
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", lambda url, **kw: rows)
    plan = fetch_site.build_list("faq")
    assert len(plan) == 1
    assert plan[0]["url"] == "http://www.subaru-faq.ru:80/faq/index.php?ELEMENT_ID=108"


def test_build_list_faq_dedups_print_and_search_highlight_variants(monkeypatch):
    # Главная находка отсева (см. отчёт): print=Y и sphrase_id — не мусор, а
    # ДУБЛИ уже учтённой страницы (печатная версия / подсветка совпадения
    # поиска того же ELEMENT_ID). На боевых данных это ~55% "адресов",
    # которые нельзя качать вторым разом.
    rows = [
        _row("http://www.subaru-faq.ru/faq/index.php?ELEMENT_ID=100"),
        _row("http://subaru-faq.ru/faq/index.php?ELEMENT_ID=100&print=Y"),
        _row("http://subaru-faq.ru/faq/index.php?ELEMENT_ID=100&sphrase_id=42"),
    ]
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", lambda url, **kw: rows)
    plan = fetch_site.build_list("faq")
    assert len(plan) == 1


def test_build_list_faq_keeps_section_listing_pages(monkeypatch):
    # SECTION_ID (категория) — НЕ служебный мусор (не login/register/search),
    # просто страница без собственного ответа; content_probe при скачивании
    # честно пометит её "нет содержимого" — на этапе плана она не
    # отбраковывается (см. отчёт, "Что НЕ отсеивается и почему").
    rows = [_row("http://www.subaru-faq.ru:80/faq/index.php?SECTION_ID=6")]
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", lambda url, **kw: rows)
    plan = fetch_site.build_list("faq")
    assert len(plan) == 1


def test_build_list_blogs_drops_service_pages(monkeypatch):
    # Реальные категории служебных страниц блогов (20.08.2026): search (форма/
    # результаты поиска), rss/rss_all (лента, не HTML), blog_edit (форма
    # редактирования), user (список блогов юзера — проверено вживую: 0
    # блоков записи), group (список блогов группы — тоже 0 блоков).
    rows = [
        _row("http://subaru-faq.ru/blogs/index.php?page=search&where=USER&q=x"),
        _row("http://subaru-faq.ru/blogs/index.php?page=rss&blog=x&type=rss2"),
        _row("http://subaru-faq.ru/blogs/index.php?page=blog_edit&blog=x&post_id=1"),
        _row("http://subaru-faq.ru/blogs/index.php?page=user&user_id=1003"),
        _row("http://subaru-faq.ru/blogs/index.php?page=group&group_id=1"),
        _row("http://subaru-faq.ru/blogs/index.php?page=post&blog=x&post_id=150"),
    ]
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", lambda url, **kw: rows)
    plan = fetch_site.build_list("blogs")
    urls = [item["url"] for item in plan]
    assert urls == ["http://subaru-faq.ru/blogs/index.php?page=post&blog=x&post_id=150"]


def test_build_list_blogs_keeps_history_page(monkeypatch):
    # page=history — единственная "административная" на вид категория,
    # которая на живой проверке (20.08.2026) реально содержит блоки записи
    # (25 штук на образце) — НЕ отсеивается заранее, в отличие от user/group.
    rows = [_row("http://subaru-faq.ru/blogs/index.php?page=history")]
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", lambda url, **kw: rows)
    plan = fetch_site.build_list("blogs")
    assert len(plan) == 1


def test_build_list_blogs_dedups_print_sphrase_and_comment_anchor(monkeypatch):
    rows = [
        _row("http://subaru-faq.ru/blogs/index.php?page=post&blog=x&post_id=150"),
        _row("http://subaru-faq.ru/blogs/index.php?page=post&blog=x&post_id=150&print=Y"),
        _row("http://subaru-faq.ru/blogs/index.php?page=post&blog=x&post_id=150&sphrase_id=9"),
        _row("http://subaru-faq.ru/blogs/index.php?page=post&blog=x&post_id=150&commentId=3"),
    ]
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", lambda url, **kw: rows)
    plan = fetch_site.build_list("blogs")
    assert len(plan) == 1


def test_build_list_calls_cdx_in_prefix_mode(monkeypatch):
    captured = {}

    def fake(url, **kw):
        captured["url"] = url
        captured["kw"] = kw
        return []

    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", fake)
    fetch_site.build_list("faq")
    assert captured["kw"].get("match_type") == "prefix"
    assert "faq" in captured["url"]


def test_build_list_each_item_has_a_local_path_under_its_section(monkeypatch):
    rows = [_row("http://subaru-faq.ru/faq/index.php?ELEMENT_ID=1")]
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", lambda url, **kw: rows)
    plan = fetch_site.build_list("faq")
    assert plan[0]["local_path"].startswith("faq/")
    assert plan[0]["local_path"].endswith(".html")


def test_build_list_local_path_is_stable_across_calls(monkeypatch):
    rows = [_row("http://subaru-faq.ru/faq/index.php?ELEMENT_ID=1")]
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", lambda url, **kw: rows)
    a = fetch_site.build_list("faq")[0]["local_path"]
    b = fetch_site.build_list("faq")[0]["local_path"]
    assert a == b


# --- признак содержимого: на реальной разметке (не на догадках) -----------

def test_faq_content_probe_detects_bitrix_catalog_element():
    # 504 из 557 адресов FAQ (90%) — современный движок Bitrix
    # (/faq/index.php?ELEMENT_ID=N), разметка — div.catalog-element, а НЕ
    # td.question/td.answer старого движка. Пропустить этот случай значило
    # бы потерять ответ почти в двух третях реальных страниц плана.
    data = (FIX / "faq_element_bitrix.html").read_bytes()
    assert fetch_site.faq_content_probe(data) is True


def test_faq_content_probe_detects_old_table_markup():
    # Старый движок (44 из 557, faq/faq.php?display=faq&nr=...) — td.question
    # (метка, затем текст) и td.answer (метка, затем текст), как и описал лид.
    data = (FIX / "faq_old_table.html").read_bytes()
    assert fetch_site.faq_content_probe(data) is True


def test_faq_content_probe_rejects_section_listing_without_an_answer():
    # SECTION_ID — категория (div.catalog-section-list), не отдельный ответ:
    # ни td.answer, ни div.catalog-element внутри нет.
    data = (FIX / "faq_section_listing.html").read_bytes()
    assert fetch_site.faq_content_probe(data) is False


def test_faq_content_probe_ignores_antibot_marker_like_the_forum_probe():
    page = (b"<html><head><script>ctSetCookie(); ctMouseData();</script></head>"
            b"<body><div class=\"catalog-element\">x" + b"y" * 2000 + b"</div></body></html>")
    assert fetch_site.faq_content_probe(page) is True


def test_blogs_content_probe_detects_post_block():
    # Индивидуальная запись (page=post) — обёрнута в div.blog-post; текст
    # записи лежит прямо внутри div.blog-post-content (тот же класс).
    data = (FIX / "blog_post.html").read_bytes()
    assert fetch_site.blogs_content_probe(data) is True


def test_blogs_content_probe_rejects_user_listing_without_post_block():
    # page=user (список блогов юзера) — проверено вживую: 0 div.blog-post.
    data = (FIX / "blog_user_listing.html").read_bytes()
    assert fetch_site.blogs_content_probe(data) is False


def test_blogs_content_probe_does_not_confuse_related_class_names():
    # "blog-post-title"/"blog-post-content" не должны ложно засчитаться как
    # "blog-post" при пустом контенте — байтовая проверка ищет ТОЧНУЮ
    # кавычку сразу после "blog-post", а не произвольный префикс класса.
    page = b'<div class="blog-post-title">x</div><div class="blog-post-comments-link">y</div>'
    assert fetch_site.blogs_content_probe(page) is False


# --- сохранение плана на диск (переживает обрыв суточного прогона) --------

def test_save_and_load_plan_roundtrip(tmp_path):
    plan = [{"section": "faq", "url": "http://x/1", "ts": "20100101000000", "local_path": "faq/aaa.html"}]
    path = fetch_site.save_plan("faq", plan, root=tmp_path)
    assert path.exists()
    loaded = fetch_site.load_plan("faq", root=tmp_path)
    assert loaded == plan


def test_load_plan_missing_file_raises_a_clear_error(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        fetch_site.load_plan("faq", root=tmp_path)


# --- fetch_all: скачивание по плану, идемпотентно, признак содержимого свой ---

def test_fetch_all_saves_file_and_records_ok(tmp_path, monkeypatch):
    plan = [{"section": "blogs", "url": "http://h/post1", "ts": "20100101000000",
             "local_path": "blogs/a.html"}]
    manifest = tmp_path / "manifest-site.jsonl"
    dest = tmp_path / "raw"
    monkeypatch.setattr(fetch_site.fetcher, "fetch_snapshot",
                         lambda ts, url, **kw: b'<div class="blog-post">content ' + b"x" * 2000 + b"</div>")
    stats = fetch_site.fetch_all(plan, dest, manifest)
    assert stats["ok"] == 1
    assert (dest / "blogs" / "a.html").exists()
    assert assets_state.load(manifest)["http://h/post1"]["status"] == "ok"


def test_fetch_all_marks_empty_when_content_probe_fails(tmp_path, monkeypatch):
    plan = [{"section": "blogs", "url": "http://h/post1", "ts": "20100101000000",
             "local_path": "blogs/a.html"}]
    manifest = tmp_path / "manifest-site.jsonl"
    dest = tmp_path / "raw"
    monkeypatch.setattr(fetch_site.fetcher, "fetch_snapshot",
                         lambda ts, url, **kw: b"<html>no post here</html>" * 100)
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots",
                         lambda url, **kw: [("20100101000000", url)])
    stats = fetch_site.fetch_all(plan, dest, manifest)
    assert stats["empty"] == 1
    assert not (dest / "blogs" / "a.html").exists()


def test_fetch_all_marks_failed_when_network_never_returns_a_body(tmp_path, monkeypatch):
    plan = [{"section": "faq", "url": "http://h/e1", "ts": "20100101000000",
             "local_path": "faq/a.html"}]
    manifest = tmp_path / "manifest-site.jsonl"
    dest = tmp_path / "raw"
    monkeypatch.setattr(fetch_site.fetcher, "fetch_snapshot", lambda ts, url, **kw: None)
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots", lambda url, **kw: [("20100101000000", url)])
    stats = fetch_site.fetch_all(plan, dest, manifest)
    assert stats["failed"] == 1


def test_fetch_all_uses_the_right_content_probe_per_section(tmp_path, monkeypatch):
    # Один и тот же прогон видит обе секции сразу — FAQ-страница должна
    # проверяться FAQ-признаком, блоговая — блоговым, а не одним на всех.
    plan = [
        {"section": "faq", "url": "http://h/faq1", "ts": "20100101000000", "local_path": "faq/a.html"},
        {"section": "blogs", "url": "http://h/blog1", "ts": "20100101000000", "local_path": "blogs/b.html"},
    ]
    manifest = tmp_path / "manifest-site.jsonl"
    dest = tmp_path / "raw"

    bodies = {
        "http://h/faq1": b'<div class="catalog-element">answer ' + b"x" * 2000 + b"</div>",
        "http://h/blog1": b'<div class="blog-post">post ' + b"x" * 2000 + b"</div>",
    }
    monkeypatch.setattr(fetch_site.fetcher, "fetch_snapshot", lambda ts, url, **kw: bodies[url])
    stats = fetch_site.fetch_all(plan, dest, manifest)
    assert stats["ok"] == 2
    assert (dest / "faq" / "a.html").exists()
    assert (dest / "blogs" / "b.html").exists()


def test_fetch_all_is_idempotent_and_skips_already_done_urls(tmp_path, monkeypatch):
    # Суточный прогон может оборваться и перезапуститься — уже скачанные
    # (ok) и уже подтверждённые пустышки (empty) не должны запрашиваться
    # у Wayback заново.
    plan = [{"section": "blogs", "url": "http://h/post1", "ts": "20100101000000",
             "local_path": "blogs/a.html"}]
    manifest = tmp_path / "manifest-site.jsonl"
    dest = tmp_path / "raw"
    assets_state.record(manifest, "http://h/post1", "blogs/a.html", "ok")

    calls = []
    monkeypatch.setattr(fetch_site.fetcher, "fetch_snapshot",
                         lambda ts, url, **kw: calls.append(url) or b"should not be used")
    stats = fetch_site.fetch_all(plan, dest, manifest)
    assert calls == []
    assert stats == {"ok": 0, "empty": 0, "failed": 0}


def test_fetch_all_respects_limit_for_a_trial_run(tmp_path, monkeypatch):
    # Пробный прогон на паре адресов перед суточным (тот же приём, что и у
    # fetch_assets --limit) — не должен трогать сеть сверх лимита.
    plan = [{"section": "blogs", "url": "http://h/%d" % i, "ts": "20100101000000",
             "local_path": "blogs/%d.html" % i} for i in range(5)]
    manifest = tmp_path / "manifest-site.jsonl"
    dest = tmp_path / "raw"
    calls = []

    def fake_fetch_snapshot(ts, url, **kw):
        calls.append(url)
        return b'<div class="blog-post">x' + b"y" * 2000 + b"</div>"

    monkeypatch.setattr(fetch_site.fetcher, "fetch_snapshot", fake_fetch_snapshot)
    stats = fetch_site.fetch_all(plan, dest, manifest, limit=2)
    assert stats["ok"] == 2
    assert len(calls) == 2


def test_fetch_all_falls_back_to_full_cdx_history_when_saved_snapshot_is_empty(tmp_path, monkeypatch):
    plan = [{"section": "blogs", "url": "http://h/post1", "ts": "20100101000000",
             "local_path": "blogs/a.html"}]
    manifest = tmp_path / "manifest-site.jsonl"
    dest = tmp_path / "raw"

    def fake_fetch_snapshot(ts, url, **kw):
        if ts == "20100101000000":
            return b"<html>empty</html>" * 100
        return b'<div class="blog-post">real content ' + b"x" * 2000 + b"</div>"

    monkeypatch.setattr(fetch_site.fetcher, "fetch_snapshot", fake_fetch_snapshot)
    monkeypatch.setattr(fetch_site.fetcher, "cdx_snapshots",
                         lambda url, **kw: [("20100101000000", url), ("20090101000000", url)])
    stats = fetch_site.fetch_all(plan, dest, manifest)
    assert stats["ok"] == 1
