"""Контракт якорей заметки: полный набор адресов, на которые ссылаются
статьи следующей фазы.

Зачем отдельный файл. Дефект C2 итогового ревью Ф2 (докстринг `mirror_blog`
обещал заголовок `## Запись` как адрес тела записи, а в коде его не было ни
в одной из 528 заметок) прожил всю фазу именно потому, что ни один тест не
утверждал «у заметки есть заголовок, адресующий тело». Тесты формата
проверяли то, что генератор пишет, а не то, что обещано читателю снаружи;
докстринг и код разошлись, и сверять было нечем.

Поэтому здесь проверяется не форматирование, а ИНТЕРФЕЙС — и двумя
способами разом:

1. заголовок присутствует в тексте заметки буквально (`_anchor_lines`);
2. сноска ровно того вида, который напишет Ф3, РАЗРЕШАЕТСЯ проверкой
   целостности (`check_mirror.check` -> 0 битых ссылок, 0 битых якорей).

Второй способ важнее первого: он проверяет ту же цепочку, что и боевой
`run check` (заголовок -> якорь -> резолв ссылки), а не только наличие
подстроки. Красный прогон этого файла до правки C2: 3 упавших теста
(`## Запись` в блоге, H1 в FAQ и сноска `#Запись`).

Список якорей ниже — единственное место, где он собран целиком; он же
воспроизведён в `docs/контракт-зеркала.md` для человека. Меняешь формат
заголовка в генераторе — этот файл падает, и это не помеха, а смысл: адрес
заметки является интерфейсом для статей, и молча его менять нельзя.
"""
from pathlib import Path

from pipeline import check_mirror, db, mirror, mirror_blog, mirror_faq

FIX_ASSETS = Path(__file__).parent / "fixtures" / "faq_assets"

# Обещанные адреса, по разделам зеркала. Ключ — как выглядит сноска Ф3,
# значение — заголовок, который обязан быть в заметке.
FORUM_ANCHORS = ["# Тема с якорями", "##### Пост 391784", "##### Пост 391785"]
FAQ_ANCHORS = ["# Чем отличаются Legacy и Outback ?", "## Вопрос", "## Ответ"]
BLOG_ANCHORS = ["# Замена масла", "## Запись", "## Комментарии",
                "##### Комментарий 640", "##### Комментарий 641"]


def _anchor_lines(md: str) -> list[str]:
    """Строки-заголовки заметки как есть (без разбора Markdown целиком —
    ровно то, что видит `check_mirror.HEADING`)."""
    return [line for line in md.split("\n") if line.startswith("#")]


def _seed(tmp_path):
    conn = db.connect(tmp_path / "contract.sqlite")
    db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Починка и ремонт')")
    conn.execute(
        "INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views, pages_expected) "
        "VALUES (42335, 19, 'Тема с якорями', 'Nikon', '2007-04-02 12:04:04', 2, 100, 1)")
    for mid, text in ((391784, "Первый пост темы."), (391785, "Второй пост темы.")):
        conn.execute(
            "INSERT INTO posts(mid, tid, page_no, author, posted_at, number, html, markdown, text) "
            "VALUES (?, 42335, 1, 'Nikon', '2007-04-02 12:04:04', '#1', '', ?, ?)",
            (mid, text, text))
    conn.execute(
        "INSERT INTO faq(engine, nr, catnr, prog, category, question, answer_md, source_url, snapshot_ts) "
        "VALUES ('old', 11, 1, 'COMMON', 'Общая информация', 'Чем отличаются Legacy и Outback ?', "
        "'Legacy Outback — одна из комплектаций.', 'http://www.subaru-faq.ru/faq/faq.php?nr=11', '20070726215648')")
    conn.execute(
        "INSERT INTO blog_posts(blog, post_id, title, author, posted_at, body_md, tags, source_url, "
        "snapshot_ts, is_excerpt, truncated) VALUES ('remont', 184, 'Замена масла', 'Пётр', "
        "'01.01.2015 10:00:00', 'Тело записи блога.', '[]', "
        "'http://www.subaru-faq.ru/blogs/index.php?page=post&blog=remont&post_id=184', '20150101100000', 0, 0)")
    for cid, parent, text in ((640, None, "Первый комментарий."), (641, 640, "Ответ на первый.")):
        conn.execute(
            "INSERT INTO blog_comments(blog, post_id, comment_id, parent_id, depth, author, posted_at, text_md) "
            "VALUES ('remont', 184, ?, ?, 0, 'scilla', '11.08.2011 10:38:01', ?)", (cid, parent, text))
    conn.commit()
    return conn


def _mirror(tmp_path):
    """Все три генератора в одно дерево вики — так же, как их зовёт
    `run.main` для команды `mirror`/`all`."""
    conn = _seed(tmp_path)
    wiki = tmp_path / "wiki"
    root = wiki / "Источники"
    mirror.write_all(conn, root, assets_root=tmp_path / "нет-файлов")
    mirror_faq.write_all(conn, root / "FAQ", assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                          assets_root=FIX_ASSETS / "assets")
    mirror_blog.write_all(conn, root / "Блоги", assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                           assets_root=FIX_ASSETS / "assets")
    return wiki, root


def test_forum_note_carries_the_promised_anchors(tmp_path):
    _wiki, root = _mirror(tmp_path)
    assert _anchor_lines((root / "Тема 42335.md").read_text(encoding="utf-8")) == FORUM_ANCHORS


def test_faq_note_carries_the_promised_anchors(tmp_path):
    # H1 у FAQ (M6 ревью) — то же, что у форума и блогов: заголовок-название.
    # Якоря `## Вопрос`/`## Ответ` обещаны Ф3 отдельно и не зависят от него.
    _wiki, root = _mirror(tmp_path)
    assert _anchor_lines((root / "FAQ" / "FAQ старый 11.md").read_text(encoding="utf-8")) == FAQ_ANCHORS


def test_blog_note_carries_the_promised_anchors(tmp_path):
    # C2 ревью: `## Запись` — единственный устойчивый адрес тела записи.
    # H1 из названия им быть не может: названия не уникальны (одно и то же
    # встречается в трёх заметках корпуса).
    _wiki, root = _mirror(tmp_path)
    assert _anchor_lines((root / "Блоги" / "Блог remont 184.md").read_text(encoding="utf-8")) == BLOG_ANCHORS


def test_every_promised_footnote_resolves(tmp_path):
    """Сноски ровно того вида, который напишет Ф3 — через ту же проверку
    целостности, что стоит в конце боевого прогона."""
    wiki, _root = _mirror(tmp_path)
    article_dir = wiki / "Статьи"
    article_dir.mkdir(parents=True)
    (article_dir / "Проба.md").write_text("\n".join([
        "Форум, пост: [[Тема 42335#Пост 391784]] и [[Тема 42335#Пост 391785]].",
        "Форум, тема целиком: [[Тема 42335]].",
        "FAQ, вопрос: [[FAQ старый 11#Вопрос]], ответ: [[FAQ старый 11#Ответ]].",
        "Блог, тело записи: [[Блог remont 184#Запись]].",
        "Блог, комментарии: [[Блог remont 184#Комментарий 640]] и [[Блог remont 184#Комментарий 641]].",
        "",
    ]), encoding="utf-8")
    found = check_mirror.check(wiki)
    assert found == {"broken_links": [], "broken_anchors": [],
                      "duplicate_anchors": [], "broken_embeds": []}


def test_anchor_texts_are_unique_inside_a_note(tmp_path):
    """Задвоенный якорь — это молча неоднозначная сноска. Проверка
    целостности такое ловит, но только на уже собранной вики; здесь то же
    утверждение стоит на выходе самих генераторов."""
    _wiki, root = _mirror(tmp_path)
    for note in sorted(root.rglob("*.md")):
        lines = _anchor_lines(note.read_text(encoding="utf-8"))
        assert len(lines) == len(set(lines)), note.name
