import yaml

from pipeline import db, mirror


def _frontmatter(md: str) -> dict:
    assert md.startswith("---\n")
    end = md.index("\n---", 4)
    return yaml.safe_load(md[4:end])


def _seed(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (10045, 19, 'Параметры коробок', 'DTR', '2007-04-02', 1, 42)")
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, text) "
                 "VALUES (53392, 10045, 1, 'DTR', '2007-04-02 12:04:04', '#1', 'первый пост')")
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, text) "
                 "VALUES (53400, 10045, 1, 'Georob', '2007-04-03 10:00:00', '#2', 'второй пост')")
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53400, 'external_image', 'http://dead.host/x.jpg', NULL, 'no_snapshot')")
    conn.commit()
    return conn


def test_block_anchor_for_every_post(tmp_path):
    md = mirror.render_thread(_seed(tmp_path), 10045)
    assert "^p53392" in md and "^p53400" in md


def test_frontmatter_has_alias_and_section(tmp_path):
    # Значения фронтматтера теперь всегда в кавычках (YAML double-quoted
    # scalar, экранированный _yaml_dquote) — сравниваем через разбор YAML,
    # а не буквальной подстрокой, само наличие кавычек не баг.
    md = mirror.render_thread(_seed(tmp_path), 10045)
    fm = _frontmatter(md)
    assert fm["aliases"] == ["Параметры коробок"]
    assert fm["раздел"] == "Типовые вопросы о Субару"


def test_lost_image_becomes_callout_not_broken_link(tmp_path):
    md = mirror.render_thread(_seed(tmp_path), 10045)
    assert "> [!missing] изображение не сохранилось" in md
    assert "![](http://dead.host/x.jpg)" not in md


def test_write_all_uses_stable_filename(tmp_path):
    out = tmp_path / "Источники"
    n = mirror.write_all(_seed(tmp_path), out)
    assert n == 1
    assert (out / "Тема 10045.md").exists()


def test_anchor_is_after_text_not_after_trailing_callout(tmp_path):
    # Решение 1: якорь ^p<MID> клеится к тексту поста, а не в конец блока —
    # иначе у поста с потерянной картинкой якорь окажется внутри коллаута,
    # и блочная сноска будет раскрывать пометку "не сохранилось" вместо
    # текста поста.
    md = mirror.render_thread(_seed(tmp_path), 10045)
    lines = md.splitlines()
    anchor_line = next(l for l in lines if "^p53400" in l)
    assert anchor_line == "второй пост ^p53400"
    # коллаут о потере картинки должен идти НИЖЕ строки с якорем
    anchor_idx = lines.index(anchor_line)
    missing_idx = next(i for i, l in enumerate(lines) if "изображение не сохранилось" in l)
    assert missing_idx > anchor_idx


def test_interface_chrome_attachment_not_rendered_and_not_flagged_missing(tmp_path):
    # Решение 3: смайлы/иконки интерфейса форума (bitrix/images,
    # images/smiley_icons, bitrix/components) не рендерятся и не помечаются
    # как утраченные — это хром форума, а не контент поста.
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'local', '/bitrix/images/forum/smile/icon_smile.gif', NULL, 'ok')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert "icon_smile" not in md
    assert md.count("[!missing]") == 1  # только внешняя картинка второго поста


def test_empty_local_path_never_renders_embed_regardless_of_status(tmp_path):
    # Решение 4: пустой local_path — всегда коллаут "не сохранилось",
    # даже если status == 'ok' (в базе есть мусорная запись именно такого вида).
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'local', '<a href=', NULL, 'ok')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert "![[" not in md
    assert "> [!missing] изображение не сохранилось" in md
    assert "<a href=" in md


def test_thread_without_posts_gets_note_with_metadata(tmp_path):
    # Решение 5: тема без постов всё равно получает заметку — с метаданными
    # из оглавления и коллаутом о том, что содержимое не сохранилось.
    conn = db.connect(tmp_path / "t2.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (999, 19, 'Пустая тема', 'DTR', '2007-04-02', 3, 10)")
    conn.commit()
    md = mirror.render_thread(conn, 999)
    assert "содержимое не сохранилось" in md
    assert "tid: 999" in md


def test_bitrix_components_getfile_is_content_not_chrome(tmp_path):
    # Правка после осмотра: bitrix/components/.../show_file.php?fid=N — это
    # тот же механизм раздачи вложений, что и getfile, а не хром интерфейса.
    # Настоящий хром (смайл bitrix/images) рядом не должен дать вообще ничего.
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'local', "
                 "'http://subaru-faq.ru/bitrix/components/bitrix/forum.interface/show_file.php?fid=123', "
                 "NULL, 'ok')")
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'local', '/bitrix/images/forum/smile/icon_smile.gif', NULL, 'ok')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert "show_file.php?fid=123" in md
    assert "> [!missing] изображение не сохранилось" in md
    assert "icon_smile" not in md


def test_duplicate_attachment_url_in_same_post_renders_once(tmp_path):
    # Дублирующиеся строки (mid, url) в attachments (реальный кейс в базе:
    # один и тот же URL встретился в разметке поста дважды) не должны давать
    # два одинаковых коллаута подряд — один URL внутри поста -> один блок.
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'external_image', 'http://host/dup.jpg', NULL, 'no_snapshot')")
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'external_image', 'http://host/dup.jpg', NULL, 'no_snapshot')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert md.count("dup.jpg") == 1


def test_unknown_replies_expected_rendered_as_unknown(tmp_path):
    # Решение 6: NULL replies_expected -> "неизвестно", не пусто и не 0.
    conn = db.connect(tmp_path / "t3.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (998, 19, 'Тема без данных', NULL, NULL, NULL, NULL)")
    conn.commit()
    md = mirror.render_thread(conn, 998)
    assert "ответов: неизвестно" in md


def test_frontmatter_survives_backslash_in_title(tmp_path):
    # Реальный случай в базе: заголовки типа «Фары GC\GF» или «215\60 R16» —
    # обратный слэш внутри двойных кавычек YAML начинает escape-последовательность,
    # если его не экранировать отдельно от кавычек.
    conn = db.connect(tmp_path / "t4.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (997, 19, 'Фары GC\\GF', 'DTR', '2007-04-02', 1, 1)")
    conn.commit()
    md = mirror.render_thread(conn, 997)
    fm = _frontmatter(md)
    assert fm["aliases"] == ["Фары GC\\GF"]


def test_frontmatter_survives_yaml_special_chars_in_author(tmp_path):
    # Реальный случай: ник начинается со спецсимвола YAML (!, [, |) — без
    # кавычек ломает весь блок фронтматтера (тег, список, блочный скаляр).
    conn = db.connect(tmp_path / "t5.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    for tid, author in ((996, "!gryk"), (995, "[68]Father"), (994, "|Bot|")):
        conn.execute(
            "INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
            "VALUES (?, 19, 'Заголовок: с двоеточием и \"кавычкой\"', ?, '2007-04-02', 1, 1)",
            (tid, author))
    conn.commit()
    for tid, author in ((996, "!gryk"), (995, "[68]Father"), (994, "|Bot|")):
        md = mirror.render_thread(conn, tid)
        fm = _frontmatter(md)
        assert fm["автор"] == author
        assert fm["aliases"] == ['Заголовок: с двоеточием и "кавычкой"']


def test_bbcode_leak_with_double_brackets_is_not_a_wikilink(tmp_path):
    # Реальный случай (18 постов, 13 тем): в текст поста утекает необработанный
    # BBCode форума с задвоенными квадратными скобками — "[[IMG]url[/img]",
    # "[[QUOTE]...", "[[/URL [URL=...]]", "[[url=...]" — html_text.plain_text
    # снимает только НАШИ markdown-ссылки/картинки, а этот мусор — буквальный
    # текст оригинального поста. Без экранирования "[[...]]" Obsidian читает
    # его как вики-ссылку на несуществующую заметку — check_mirror.check
    # (задача 8) находил такие как broken_links на реальном корпусе.
    conn = db.connect(tmp_path / "t7.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (992, 19, 'Тема с мусором', 'DTR', '2007-04-02', 1, 1)")
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, text) "
                 "VALUES (53500, 992, 1, 'DTR', '2007-04-02 12:04:04', '#1', "
                 "'фото тут [[IMG]http://example.com/x.jpg[/img]')")
    conn.commit()
    md = mirror.render_thread(conn, 992)
    assert "[[IMG]" not in md
    assert "\\[\\[IMG]" in md
    # свою собственную сноску-якорь ("^p53500") экранирование не должно портить
    assert "^p53500" in md


def test_all_generated_frontmatter_parses_as_yaml(tmp_path):
    # Стресс-тест: смесь всех проблемных случаев сразу в одной теме.
    conn = db.connect(tmp_path / "t6.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Раздел: с \"кавычкой\"')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (993, 19, '215\\60 R16 ''RUS'' SUBaruZERO', '''RUS'' SUBaruZERO', "
                 "'2007-04-02', NULL, 1)")
    conn.commit()
    md = mirror.render_thread(conn, 993)
    fm = _frontmatter(md)
    assert fm["автор"] == "'RUS' SUBaruZERO"
    assert fm["раздел"] == 'Раздел: с "кавычкой"'
    assert fm["aliases"] == ["215\\60 R16 'RUS' SUBaruZERO"]
