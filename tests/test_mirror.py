from pipeline import db, mirror


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
    md = mirror.render_thread(_seed(tmp_path), 10045)
    assert 'aliases: ["Параметры коробок"]' in md
    assert "раздел: Типовые вопросы о Субару" in md


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
