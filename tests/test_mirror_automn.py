"""Тесты генератора зеркала «Руководство» (третий источник — живое
руководство automn.ru, скачанное `tools/fetch_automn.py`).

Фикстуры HTML в этом файле — СВОИ, придуманные для теста, а не куски
настоящего сайта: разметка (классы `content`/`article-content-text`/
`content-header`, структура `#contentblock`) списана с живых страниц
(разведка перед правкой), но текст внутри — синтетический пример
процедуры/спецификации, не дословный текст источника.
"""
import json
from pathlib import Path

import yaml

from pipeline import check_mirror, mirror, mirror_automn, mirror_blog

# Минимальный валидный JPEG/PNG — для тестов копирования картинок (та же
# идея, что и в других тестовых файлах проекта: байты определяют тип по
# сигнатуре `attachments.sniff`, а не по расширению в адресе).
_JPEG_BYTES = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000002000100"
    "ffff03000006000557bfabd40000000049454e44ae426082")


def _page(title: str, body: str, manual_path: str = "subaru-legacy-outback") -> str:
    return """<!DOCTYPE html>
<html><head><title>%s</title></head><body>
<div id="contentblock">
<div class="left-content"><div class="ser">меню сайта, не контент</div></div>
<div class="content">
<div class="content-header">
<h1>%s</h1>
<div class="pathway"><span class="bgway"><a href="/automanuals.html">Руководства</a></span></div>
</div>
<div class="article-content-text">
%s
</div>
</div>
<div class="right">реклама, не контент</div>
</div>
</body></html>""" % (title, title, body)


def _frontmatter(md: str) -> dict:
    lines = md.split("\n")
    assert lines[0] == "---"
    end = next(i for i in range(1, len(lines)) if lines[i] == "---")
    return yaml.safe_load("\n".join(lines[1:end]))


def _anchor_lines(md: str) -> list[str]:
    return [line for line in md.split("\n") if line.startswith("#")]


# --- parse_page: заголовок / руководство / номер главы --------------------

def test_parse_page_extracts_title_manual_and_chapter_number():
    html = _page("11.13 Снятие узла подвески", "<p>Простой абзац текста процедуры.</p>")
    page = mirror_automn.parse_page(html, "http://automn.ru/subaru-legacy-outback/subaru-1-1.m_id-1.html")
    assert page["ok"] is True
    assert page["manual"] == "legacy-outback"
    assert page["title"] == "11.13 Снятие узла подвески"
    assert page["chapter_number"] == "11.13"
    assert "Простой абзац текста процедуры." in page["body_md"]


def test_parse_page_forester_manual_and_no_number_root_page():
    html = _page("Автомобили Subaru Forester (Субару Форестер) 1997-2005 г. в.",
                 "<p>Вводный текст.</p>")
    page = mirror_automn.parse_page(html, "http://automn.ru/subaru-forester/index.html")
    assert page["manual"] == "forester"
    assert page["chapter_number"] is None


def test_parse_page_falls_back_to_content_text_variant():
    """Категорийные страницы (54 из 805 на живом корпусе) несут тело в
    `content-text`, а не в `article-content-text` — обе ветки контента."""
    html = """<!DOCTYPE html><html><body>
<div id="contentblock">
<div class="left-content"></div>
<div class="content">
<div class="content-header"><h1>3. Текущее обслуживание</h1></div>
<div class="content-text"><p>Описание раздела.</p></div>
</div>
</div></body></html>"""
    page = mirror_automn.parse_page(html, "http://automn.ru/subaru-forester/autocategory-1-1.html")
    assert page["ok"] is True
    assert "Описание раздела." in page["body_md"]


def test_parse_page_missing_content_block_is_honest_failure():
    html = "<html><body><p>Совсем не та страница.</p></body></html>"
    page = mirror_automn.parse_page(html, "http://automn.ru/subaru-forester/x.html")
    assert page["ok"] is False


# --- заголовки внутри тела: демоция, а не якорь ----------------------------

def test_internal_subheading_is_demoted_to_bold_not_a_heading():
    html = _page("6.2 Раздел с подзаголовком",
                 "<h3>Внутренний подраздел</h3><p>Текст после подраздела.</p>")
    page = mirror_automn.parse_page(html, "http://automn.ru/subaru-legacy-outback/x.html")
    body = page["body_md"]
    assert "**Внутренний подраздел**" in body
    # НИ ОДНОЙ строки вида "### ..." — иначе якорный контракт заметки
    # (H1 + "## Текст") получил бы третий, непредвиденный заголовок.
    assert not any(line.strip().startswith("#") for line in body.split("\n"))


def test_note_anchor_contract_is_exactly_h1_and_text_heading(tmp_path):
    pages_dir, manifest = _write_corpus(tmp_path, [
        ("http://automn.ru/subaru-legacy-outback/a.html", "a.html",
         _page("11.13 Процедура", "<h4>Подшаг</h4><p>Текст.</p>")),
    ])
    out = tmp_path / "Руководство"
    mirror_automn.write_all(pages_dir, manifest, out)
    md = (out / "Руководство Legacy Outback 11.13 Процедура.md").read_text(encoding="utf-8")
    assert _anchor_lines(md) == ["# 11.13 Процедура", "## Текст"]


def test_promised_footnote_resolves_through_check_mirror(tmp_path):
    """Второй, более важный способ проверки контракта якоря (докстринг
    `docs/контракт-зеркала.md`, §1: «второй способ важнее первого») — не
    только буквальное наличие заголовка в тексте, а то, что сноска РОВНО
    ТОГО вида, который напишет статья, разрешается `check_mirror.check` в
    собранном дереве вики: 0 битых ссылок/якорей/задвоенных якорей/вставок."""
    pages_dir, manifest = _write_corpus(tmp_path, [
        ("http://automn.ru/subaru-legacy-outback/a.html", "a.html",
         _page("11.13 Процедура", "<p>Текст процедуры.</p>")),
    ])
    wiki = tmp_path / "wiki"
    mirror_automn.write_all(pages_dir, manifest, wiki / "Источники" / "Руководство")
    article_dir = wiki / "Статьи"
    article_dir.mkdir(parents=True)
    (article_dir / "Проба.md").write_text(
        "Ссылка на страницу целиком: [[Руководство Legacy Outback 11.13 Процедура]].\n"
        "Ссылка на тело: [[Руководство Legacy Outback 11.13 Процедура#Текст]].\n",
        encoding="utf-8")
    found = check_mirror.check(wiki)
    assert found == {"broken_links": [], "broken_anchors": [],
                      "duplicate_anchors": [], "broken_embeds": []}


# --- таблицы: данные -> markdown, разметка -> поток ------------------------

def test_data_table_becomes_markdown_pipe_table_without_losing_numbers():
    body = """
    <table>
      <tr><td>Деталь</td><td>Момент, Н·м</td></tr>
      <tr><td>Болт крепления А</td><td>25</td></tr>
      <tr><td>Болт крепления Б</td><td>108</td></tr>
    </table>
    """
    html = _page("8.1 Спецификации", body)
    page = mirror_automn.parse_page(html, "http://automn.ru/subaru-legacy-outback/x.html")
    md = page["body_md"]
    lines = [l for l in md.split("\n") if l.strip().startswith("|")]
    assert len(lines) == 4  # заголовок + разделитель + 2 строки данных
    assert lines[1].replace(" ", "").startswith("|---")
    assert "25" in lines[2] and "108" not in lines[2]
    assert "108" in lines[3] and "25" not in lines[3]


def test_footnote_superscript_does_not_merge_into_the_number():
    """Живая находка верификации на реальном корпусе (1 страница из 805,
    спецификации размеров кузова): исходник ставит сноску-надстрочник
    ВПЛОТНУЮ к числу без пробела — `1420<sup>1)</sup>`. Без разделителя
    цифра сноски дописывается к концу настоящего значения и регэксп числа
    читает «14201» как одно число вместо «1420» + отдельная сноска «1)» —
    ровно тот класс потери, которого требование задачи прямо опасается."""
    body = "<table><tr><td>1440, 1420<sup>1)</sup></td><td>2</td></tr>" \
           "<tr><td>3</td><td>4</td></tr></table>"
    html = _page("8.1 Спецификации", body)
    page = mirror_automn.parse_page(html, "http://automn.ru/subaru-legacy-outback/x.html")
    md = page["body_md"]
    assert "14201" not in md
    assert "1420" in md


def test_colspan_and_rowspan_are_expanded_without_losing_values():
    body = """
    <table>
      <tr><td colspan="2">Заголовок над двумя столбцами</td></tr>
      <tr><td rowspan="2">Общее для двух строк</td><td>111</td></tr>
      <tr><td>222</td></tr>
    </table>
    """
    html = _page("8.1 Спецификации", body)
    page = mirror_automn.parse_page(html, "http://automn.ru/subaru-legacy-outback/x.html")
    md = page["body_md"]
    rows = [l for l in md.split("\n") if l.strip().startswith("|")]
    # 4 исходные логические строки таблицы (заголовок + разделитель + 2 данных)
    assert len(rows) == 4
    assert rows[2].count("Общее для двух строк") == 1
    assert "111" in rows[2]
    assert rows[3].count("Общее для двух строк") == 1
    assert "222" in rows[3]


def test_layout_table_with_image_is_flowed_not_tabulated():
    body = """
    <table>
      <tr>
        <td><img src="http://s7.automn.ru/subaru-legacy-outback/pict/001.jpg"></td>
        <td>Подпись к схеме.</td>
      </tr>
    </table>
    """
    html = _page("11.13 Процедура", body)
    page = mirror_automn.parse_page(html, "http://automn.ru/subaru-legacy-outback/x.html")
    md = page["body_md"]
    assert not any(l.strip().startswith("|") for l in md.split("\n"))
    assert "Подпись к схеме." in md
    assert "http://s7.automn.ru/subaru-legacy-outback/pict/001.jpg" in md


def test_table_pipe_character_in_cell_is_escaped():
    body = "<table><tr><td>А|Б</td><td>1</td></tr><tr><td>В</td><td>2</td></tr></table>"
    html = _page("8.1 Спецификации", body)
    page = mirror_automn.parse_page(html, "http://automn.ru/subaru-legacy-outback/x.html")
    md = page["body_md"]
    assert "А\\|Б" in md


# --- картинки: хром вырезается, контент ищется в манифесте -----------------

def test_chrome_icon_is_dropped_and_content_image_kept_as_marker():
    body = ('<p>Текст.<img src="http://s7.automn.ru/images/warning.gif"> '
            '<img src="http://s7.automn.ru/subaru-legacy-outback/pict/002.jpg"></p>')
    html = _page("11.13 Процедура", body)
    page = mirror_automn.parse_page(html, "http://automn.ru/subaru-legacy-outback/x.html")
    md = page["body_md"]
    assert "warning.gif" not in md
    assert "http://s7.automn.ru/subaru-legacy-outback/pict/002.jpg" in md


def _write_corpus(tmp_path, entries) -> tuple[Path, Path]:
    """`entries` — список `(url, filename, html_or_bytes)`. Пишет файлы и
    манифест `data/automn/manifest.jsonl`-совместимого вида."""
    pages_dir = tmp_path / "files"
    pages_dir.mkdir(parents=True, exist_ok=True)
    manifest = tmp_path / "manifest.jsonl"
    with manifest.open("w", encoding="utf-8") as fh:
        for url, filename, content in entries:
            path = pages_dir / filename
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
            fh.write(json.dumps({"url": url, "status": "ok", "file": filename}, ensure_ascii=False) + "\n")
    return pages_dir, manifest


def test_write_all_copies_found_image_and_marks_missing_one_honestly(tmp_path):
    img_url_found = "http://s7.automn.ru/subaru-legacy-outback/pict/003.jpg"
    img_url_missing = "http://s7.automn.ru/subaru-legacy-outback/pict/004.jpg"
    body = ("<p>Текст с картинкой <img src=\"%s\"> и утраченной "
            "<img src=\"%s\"></p>") % (img_url_found, img_url_missing)
    page_url = "http://automn.ru/subaru-legacy-outback/subaru-1-1.m_id-1.html"
    pages_dir, manifest = _write_corpus(tmp_path, [
        (page_url, "page.html", _page("11.13 Процедура", body)),
        (img_url_found, "003.jpg", _JPEG_BYTES),
    ])
    out = tmp_path / "Руководство"
    stats = mirror_automn.write_all(pages_dir, manifest, out)
    md = (out / "Руководство Legacy Outback 11.13 Процедура.md").read_text(encoding="utf-8")
    assert "![[assets/" in md
    assert img_url_missing in md  # честная пометка об утрате несёт исходный адрес
    assert stats["картинок_вставлено"] == 1
    assert stats["картинок_утрачено"] == 1
    assets = list((out / "assets").iterdir())
    assert len(assets) == 1
    assert assets[0].read_bytes() == _JPEG_BYTES


def test_write_all_names_and_frontmatter(tmp_path):
    page_url = "http://automn.ru/subaru-forester/subaru-1-1.m_id-1.html"
    pages_dir, manifest = _write_corpus(tmp_path, [
        (page_url, "page.html", _page("6.2.5 Снятие/установка корпуса", "<p>Текст.</p>",
                                       manual_path="subaru-forester")),
    ])
    out = tmp_path / "Руководство"
    mirror_automn.write_all(pages_dir, manifest, out)
    names = [p.name for p in out.glob("*.md")]
    assert len(names) == 1
    name = names[0]
    # "/" запрещён в имени файла — заменён, без потери остального текста.
    assert "/" not in name
    assert name.startswith("Руководство Forester 6.2.5 Снятие")
    md = (out / name).read_text(encoding="utf-8")
    fm = _frontmatter(md)
    assert fm["руководство"] == "Forester"
    assert fm["номер"] == "6.2.5"
    assert fm["адрес"] == page_url
    assert fm["aliases"] == ["6.2.5 Снятие/установка корпуса"]


def test_duplicate_generated_name_raises_and_leaves_mirror_untouched(tmp_path):
    url_a = "http://automn.ru/subaru-legacy-outback/subaru-1-1.m_id-1.html"
    url_b = "http://automn.ru/subaru-legacy-outback/subaru-2-1.m_id-1.html"
    pages_dir, manifest = _write_corpus(tmp_path, [
        (url_a, "a.html", _page("11.13 Одинаковое имя", "<p>Первая страница.</p>")),
        (url_b, "b.html", _page("11.13 Одинаковое имя", "<p>Вторая страница.</p>")),
    ])
    out = tmp_path / "Руководство"
    try:
        mirror_automn.write_all(pages_dir, manifest, out)
        assert False, "ожидалась RuntimeError на дублирующемся имени"
    except RuntimeError:
        pass
    assert not out.exists() or not list(out.glob("*.md"))


def test_write_all_removes_stale_notes_on_rebuild(tmp_path):
    url_a = "http://automn.ru/subaru-legacy-outback/a.html"
    url_b = "http://automn.ru/subaru-legacy-outback/b.html"
    pages_dir, manifest = _write_corpus(tmp_path, [
        (url_a, "a.html", _page("1.1 Первая", "<p>Текст первой.</p>")),
        (url_b, "b.html", _page("1.2 Вторая", "<p>Текст второй.</p>")),
    ])
    out = tmp_path / "Руководство"
    mirror_automn.write_all(pages_dir, manifest, out)
    assert len(list(out.glob("*.md"))) == 2

    # Вторая страница исчезла из манифеста (пример: перекачали без неё).
    manifest.write_text(
        json.dumps({"url": url_a, "status": "ok", "file": "a.html"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    mirror_automn.write_all(pages_dir, manifest, out)
    remaining = [p.name for p in out.glob("*.md")]
    assert len(remaining) == 1
    assert "Первая" in remaining[0]


def test_empty_or_malformed_page_gets_honest_marker_and_is_counted(tmp_path):
    url = "http://automn.ru/subaru-legacy-outback/broken.html"
    pages_dir, manifest = _write_corpus(tmp_path, [
        (url, "broken.html", "<html><body>не та страница вовсе</body></html>"),
    ])
    out = tmp_path / "Руководство"
    stats = mirror_automn.write_all(pages_dir, manifest, out)
    assert stats["пустых"] == 1
    assert stats["заметок"] == 1
    md = next(out.glob("*.md")).read_text(encoding="utf-8")
    assert mirror_blog.BODY_LOST in md


def test_check_collisions_flags_existing_wiki_name(tmp_path):
    """Требование 2: имя заметки — функция страницы, но обязано быть
    проверено на совпадение с уже существующими заметками/алиасами вики —
    готовая проверка `check_mirror.title_collisions`."""
    wiki = tmp_path / "wiki"
    src = wiki / "Источники"
    src.mkdir(parents=True)
    (src / "Тема 1.md").write_text(
        '---\naliases: ["11.13 Процедура"]\n---\n\n# Тема\n', encoding="utf-8")
    auto_dir = src / "Руководство"
    auto_dir.mkdir()
    (auto_dir / "Руководство Legacy Outback 11.13 Процедура.md").write_text(
        "---\naliases: [\"11.13 Процедура\"]\n---\n\n# 11.13 Процедура\n\n## Текст\n", encoding="utf-8")
    found = mirror_automn.check_collisions(wiki)
    assert "11.13 Процедура" in found
