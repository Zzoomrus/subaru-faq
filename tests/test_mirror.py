import yaml

from pipeline import db, mirror


def _frontmatter(md: str) -> dict:
    """Отрезает фронтматтер по ЗАКРЫВАЮЩЕЙ СТРОКЕ `---`, а не по первому
    вхождению подстроки `\n---` (отложенная находка №8 ревью): у четырёх тем
    корпуса `---` стоит внутри названия («2010/03/13 --- ТАНКОДРОМ НИИ 21»),
    и наивный поиск обрезал бы фронтматтер по середине значения, давая
    ложную уверенность в тесте.
    """
    lines = md.split("\n")
    assert lines[0] == "---"
    end = next(i for i in range(1, len(lines)) if lines[i] == "---")
    return yaml.safe_load("\n".join(lines[1:end]))


def _seed(tmp_path, name="t.sqlite"):
    conn = db.connect(tmp_path / name); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (10045, 19, 'Параметры коробок', 'DTR', '2007-04-02', 1, 42)")
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (53392, 10045, 1, 'DTR', '2007-04-02 12:04:04', '#1', 'первый пост', 'первый пост')")
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (53400, 10045, 1, 'Georob', '2007-04-03 10:00:00', '#2', 'второй пост', 'второй пост')")
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53400, 'external_image', 'http://dead.host/x.jpg', NULL, 'pending')")
    conn.commit()
    return conn


def _section(md: str, mid: int) -> list[str]:
    """Строки заметки от заголовка поста до следующего заголовка — ровно то,
    что Obsidian считает секцией и втягивает по ссылке `[[Тема N#Пост MID]]`.
    """
    lines = md.split("\n")
    start = lines.index("##### Пост %d" % mid)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("#"):
            return lines[start:i]
    return lines[start:]


def test_post_heading_is_the_anchor_and_author_goes_below(tmp_path):
    # Ruling 29: заголовок поста — ровно `##### Пост <MID>` (коротко,
    # стабильно, уникально внутри заметки и без символов `# | ^ [[ ]]`,
    # ломающих ссылку); автор и дата — строкой ниже.
    md = mirror.render_thread(_seed(tmp_path), 10045)
    assert "##### Пост 53392" in md
    lines = md.split("\n")
    i = lines.index("##### Пост 53392")
    assert lines[i + 1] == ""
    assert lines[i + 2] == "*DTR · 02.04.2007 12:04:04 · #1*"


def test_no_block_anchors_left(tmp_path):
    # Два механизма адресации сразу — источник расхождения: убираем блочные.
    md = mirror.render_thread(_seed(tmp_path), 10045)
    assert "^p53392" not in md and "^p53400" not in md


def test_multiparagraph_post_is_covered_by_its_heading_anchor(tmp_path):
    # I2: блочный якорь `^p<MID>` адресовал только ПОСЛЕДНИЙ абзац, а
    # многоабзацных постов 19140 из 48689. Заголовочный якорь адресует
    # весь пост до следующего заголовка — проверяем, что все абзацы
    # действительно внутри секции.
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (53410, 10045, 1, 'Ivan', '2007-04-04 10:00:00', '#3', "
                 "'первый абзац\n\nвторой абзац\n\n> цитата чужих слов', 'плоско')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    section = _section(md, 53410)
    assert "первый абзац" in section
    assert "второй абзац" in section
    assert "> цитата чужих слов" in section


def test_body_comes_from_markdown_column_so_quotes_stay_blockquotes(tmp_path):
    # I1: в заметку идёт posts.markdown, а не posts.text — иначе цитата
    # чужих слов неотличима от слов автора поста.
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (53420, 10045, 1, 'Petr', '2007-04-05 10:00:00', '#4', "
                 "'> KOLESO пишет:\n> вопрос\n\nответ [мануал](http://host/man.pdf)', "
                 "'KOLESO пишет: вопрос ответ мануал')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert "> KOLESO пишет:" in md
    assert "[мануал](http://host/man.pdf)" in md, "URL ссылки не должен теряться"


def test_posts_are_ordered_by_mid_not_by_page_no(tmp_path):
    # I3: посты со `message_*`-снимка получают page_no=1 жёстко, и при
    # сортировке (page_no, mid) всплывают в начало темы — на корпусе это
    # ломало хронологию в 5 темах (26922, 32487, 34559, 36559, 40626).
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (99999, 10045, 1, 'Late', '2008-01-01 10:00:00', '#9', 'поздний пост', 'поздний пост')")
    conn.execute("UPDATE posts SET page_no = 2 WHERE mid = 53400")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    order = [int(l.removeprefix("##### Пост ")) for l in md.split("\n") if l.startswith("##### Пост ")]
    assert order == [53392, 53400, 99999]


def test_forum_smiley_never_reaches_the_note_body(tmp_path):
    # markdown-версия тела показывает смайлы как `![](/bitrix/images/...)` —
    # они должны исчезать так же, как исчезали из plain_text.
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (53430, 10045, 1, 'Petr', '2007-04-06 10:00:00', '#5', "
                 "'смешно ![](/bitrix/images/forum/smile/icon_lol.gif) правда', 'смешно правда')")
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53430, 'chrome', '/bitrix/images/forum/smile/icon_lol.gif', NULL, 'skip')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert "icon_lol" not in md
    assert "смешно" in md and "правда" in md


def test_content_image_is_rendered_once_by_the_attachment_mechanism(tmp_path):
    # Картинки в заметке живут ровно одним механизмом — блоками из
    # `attachments` (вставка или пометка об утрате). Inline-разметка
    # `![](...)` из тела снимается, иначе контентная картинка выводилась бы
    # дважды: битой вставкой в тексте и коллаутом ниже.
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (53440, 10045, 1, 'Petr', '2007-04-07 10:00:00', '#6', "
                 "'вот фото ![](http://dead.host/foto.jpg) смотрите', 'вот фото смотрите')")
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53440, 'external_image', 'http://dead.host/foto.jpg', NULL, 'pending')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert md.count("foto.jpg") == 1
    assert "![](http://dead.host/foto.jpg)" not in md
    assert "изображение не сохранилось: http://dead.host/foto.jpg" in md


def test_image_with_file_renders_in_place():
    # Задача 4: картинка встаёт на своё место в тексте, а не в конец поста.
    md = mirror.render_post_body(
        "До ![](http://h/x.jpg) после",
        {"http://h/x.jpg": {"local_path": "h/abc.jpg", "status": "ok"}})
    assert md.index("До") < md.index("![[h/abc.jpg]]") < md.index("после")


def test_image_without_file_becomes_inline_note():
    # Имя из брифа задачи было "inline_callout" — по факту это НЕ callout
    # (двухстрочный `> [!missing]` не встаёт посреди предложения), а
    # компактная однострочная пометка на месте картинки.
    md = mirror.render_post_body(
        "До ![](http://h/x.jpg) после",
        {"http://h/x.jpg": {"local_path": None, "status": "no_snapshot"}})
    assert "![[" not in md
    assert "изображение не сохранилось" in md
    assert md.index("До") < md.index("изображение не сохранилось") < md.index("после")


def test_chrome_image_disappears_without_trace():
    md = mirror.render_post_body(
        "Смешно ![](/bitrix/images/forum/smile/icon_smile.gif) очень", {})
    assert md == "Смешно очень" or md == "Смешно  очень"


def test_same_url_twice_in_one_post_renders_at_both_positions():
    # Позиционный рендеринг — это рендеринг ПО ВХОЖДЕНИЮ в тексте, а не по
    # строке в attachments. На корпусе 8 постов реально вставляют одну и ту
    # же картинку дважды (не баг парсера — сам автор поста продублировал);
    # раньше это схлопывалось в одну вставку в конце, теперь — как в тексте.
    md = mirror.render_post_body(
        "раз ![](http://h/x.jpg) и два ![](http://h/x.jpg) готово",
        {"http://h/x.jpg": {"local_path": "h/abc.jpg", "status": "ok"}})
    assert md.count("![[h/abc.jpg]]") == 2
    assert md.index("раз") < md.index("и два")


def test_adjacent_lost_images_without_gap_dont_glue_into_one_line():
    # Найдено ревью: реальный паттерн форума — вставленная галерея, где
    # несколько `![](url)` идут подряд без пробела/переноса между ними.
    # Без разделителя между соседними подстановками пометки сливались бы в
    # одну нечитаемую строку `(...)(...)(...)`. На корпусе — 85 постов,
    # 244 такие пары (независимый пересчёт совпадает по порядку величины с
    # цифрой ревьюера 76/233 — расхождение из-за разных фильтров выборки).
    md = mirror.render_post_body(
        "Галерея:![](http://h/1.jpg)![](http://h/2.jpg)готово",
        {"http://h/1.jpg": {"local_path": None, "status": "no_snapshot"},
         "http://h/2.jpg": {"local_path": None, "status": "no_snapshot"}})
    assert ")(" not in md
    assert "изображение не сохранилось: http://h/1.jpg" in md
    assert "изображение не сохранилось: http://h/2.jpg" in md
    assert md.index("http://h/1.jpg") < md.index("http://h/2.jpg")


def test_adjacent_embeds_without_gap_stay_on_separate_lines():
    # Та же склейка ждала бы и настоящие вставки файлов `![[путь]]` —
    # проверяем позитивный путь тоже, не только пометки об утрате.
    md = mirror.render_post_body(
        "Галерея:![](http://h/1.jpg)![](http://h/2.jpg)готово",
        {"http://h/1.jpg": {"local_path": "h/1.jpg", "status": "ok"},
         "http://h/2.jpg": {"local_path": "h/2.jpg", "status": "ok"}})
    assert "![[h/1.jpg]]![[h/2.jpg]]" not in md
    assert "![[h/1.jpg]]" in md and "![[h/2.jpg]]" in md
    assert md.index("![[h/1.jpg]]") < md.index("![[h/2.jpg]]")


def test_single_lost_image_gets_no_extra_blank_lines():
    # Разделитель нужен ТОЛЬКО между соседними подстановками — одиночная
    # картинка не должна обрасти лишними пустыми строками.
    md = mirror.render_post_body(
        "До ![](http://h/x.jpg) после",
        {"http://h/x.jpg": {"local_path": None, "status": "no_snapshot"}})
    assert "\n\n" not in md


def test_orphan_attachment_without_inline_tag_still_not_lost():
    # `attachments` знает про URL, которого в тексте поста нет вовсе (13 из
    # 8960 на корпусе — картинка обёрнута в ссылку с непустым текстом,
    # `to_markdown` рендерит её как обычную ссылку, а `images()` всё равно
    # находит src). Молча терять её нельзя (глобальное ограничение «ни
    # одной битой картинки») — она идёт в конец тела как явная пометка.
    md = mirror.render_post_body(
        "текст без картинок вовсе",
        {"http://h/orphan.jpg": {"local_path": None, "status": "no_snapshot"}})
    assert "изображение не сохранилось: http://h/orphan.jpg" in md


def test_render_thread_places_image_inline_when_file_exists(tmp_path):
    # Интеграционная проверка через полный render_thread, а не только
    # юнит-функцию: реальный ![](url) в теле поста, найденный файл.
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (53470, 10045, 1, 'Petr', '2007-04-10 10:00:00', '#7', "
                 "'Смотри схему ![](http://h/scheme.jpg) вот тут', 'x')")
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53470, 'external_image', 'http://h/scheme.jpg', 'h/scheme123.jpg', 'ok')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    section = _section(md, 53470)
    joined = "\n".join(section)
    assert joined.index("Смотри схему") < joined.index("![[h/scheme123.jpg]]") < joined.index("вот тут")


def test_heading_like_lines_inside_post_are_escaped(tmp_path):
    # 9 постов корпуса содержат строки, которые Markdown прочтёт как
    # заголовок: 2 ATX (`# ...`) и 7 setext (строка из дефисов сразу под
    # текстом). Любой такой заголовок оборвал бы секцию поста — то есть
    # ссылка `[[Тема N#Пост MID]]` раскрыла бы только начало поста.
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (53450, 10045, 1, 'Petr', '2007-04-08 10:00:00', '#7', "
                 "'# Не поставляется\n\nхвост поста', 'x')")
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (53460, 10045, 1, 'Petr', '2007-04-09 10:00:00', '#8', "
                 "'подключил 12В, и о чудо\n--------------------\n\n> цитата\n> ---\n\nхвост', 'x')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert "хвост поста" in _section(md, 53450)
    assert "хвост" in _section(md, 53460)
    assert "\n# Не поставляется" not in md


def test_frontmatter_has_alias_and_section(tmp_path):
    md = mirror.render_thread(_seed(tmp_path), 10045)
    fm = _frontmatter(md)
    assert fm["aliases"] == ["Параметры коробок"]
    assert fm["раздел"] == "Типовые вопросы о Субару"


def test_lost_image_becomes_compact_note_not_broken_link(tmp_path):
    md = mirror.render_thread(_seed(tmp_path), 10045)
    assert "изображение не сохранилось: http://dead.host/x.jpg" in md
    assert "![](http://dead.host/x.jpg)" not in md
    # Компактно — однострочная пометка, а не двухстрочный коллаут.
    assert "[!missing]" not in md


def test_write_all_uses_stable_filename(tmp_path):
    out = tmp_path / "Источники"
    n = mirror.write_all(_seed(tmp_path), out)
    assert n == 1
    assert (out / "Тема 10045.md").exists()


def test_write_all_removes_notes_of_vanished_threads(tmp_path):
    # Заметки исчезнувших tid не должны оставаться мусором от прошлых
    # прогонов: имя заметки детерминировано, значит лишнее видно точно.
    out = tmp_path / "Источники"
    conn = _seed(tmp_path)
    mirror.write_all(conn, out)
    stale = out / "Тема 777.md"
    stale.write_text("осталось от прошлого прогона", encoding="utf-8")
    foreign = out / "Тормоза GC8.md"
    foreign.write_text("статья следующей фазы, не наша", encoding="utf-8")
    mirror.write_all(conn, out)
    assert not stale.exists()
    assert foreign.exists(), "чужие заметки трогать нельзя — только `Тема <TID>.md`"


def test_lost_image_notes_stay_inside_the_post_section(tmp_path):
    # Смена семантики относительно прежнего «Решения 1»: якорь адресует
    # весь пост, значит пометки об утраченных картинках теперь ВНУТРИ
    # секции поста — это осознанно, они относятся именно к этому посту.
    md = mirror.render_thread(_seed(tmp_path), 10045)
    section = _section(md, 53400)
    assert any("изображение не сохранилось" in l for l in section)
    assert "второй пост" in section


def test_interface_chrome_attachment_not_rendered_and_not_flagged_missing(tmp_path):
    # Хром форума (kind='chrome' по единому правилу pipeline.attachments)
    # не рендерится и не помечается утратой — терять там нечего.
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'chrome', '/bitrix/images/forum/smile/icon_smile.gif', NULL, 'skip')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert "icon_smile" not in md
    assert md.count("изображение не сохранилось") == 1  # только внешняя картинка второго поста


def test_empty_local_path_never_renders_embed_regardless_of_status(tmp_path):
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'local', '<a href=', NULL, 'ok')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert "![[" not in md
    assert "изображение не сохранилось: <a href=" in md
    assert "<a href=" in md


def test_thread_without_posts_gets_note_with_metadata(tmp_path):
    conn = db.connect(tmp_path / "t2.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (999, 19, 'Пустая тема', 'DTR', '2007-04-02', 3, 10)")
    conn.commit()
    md = mirror.render_thread(conn, 999)
    assert "содержимое не сохранилось" in md
    assert "tid: 999" in md


def test_bitrix_components_getfile_is_content_not_chrome(tmp_path):
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'local', "
                 "'http://subaru-faq.ru/bitrix/components/bitrix/forum.interface/show_file.php?fid=123', "
                 "NULL, 'pending')")
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'chrome', '/bitrix/images/forum/smile/icon_smile.gif', NULL, 'skip')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert "show_file.php?fid=123" in md
    assert "изображение не сохранилось: " in md
    assert "icon_smile" not in md


def test_duplicate_attachment_url_in_same_post_renders_once(tmp_path):
    conn = _seed(tmp_path)
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'external_image', 'http://host/dup.jpg', NULL, 'pending')")
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (53392, 'external_image', 'http://host/dup.jpg', NULL, 'pending')")
    conn.commit()
    md = mirror.render_thread(conn, 10045)
    assert md.count("dup.jpg") == 1


def test_unknown_replies_expected_rendered_as_unknown(tmp_path):
    conn = db.connect(tmp_path / "t3.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (998, 19, 'Тема без данных', NULL, NULL, NULL, NULL)")
    conn.commit()
    md = mirror.render_thread(conn, 998)
    assert "ответов: неизвестно" in md


def test_frontmatter_survives_backslash_in_title(tmp_path):
    conn = db.connect(tmp_path / "t4.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (997, 19, 'Фары GC\\GF', 'DTR', '2007-04-02', 1, 1)")
    conn.commit()
    md = mirror.render_thread(conn, 997)
    fm = _frontmatter(md)
    assert fm["aliases"] == ["Фары GC\\GF"]


def test_frontmatter_survives_dashes_inside_title(tmp_path):
    # Ruling 25: у четырёх тем `---` стоит внутри названия. Фронтматтер
    # обязан читаться целиком, а не обрываться по этой строке.
    conn = db.connect(tmp_path / "t8.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Встречи')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (991, 19, '2010/03/13 --- ТАНКОДРОМ НИИ 21', 'DTR', '2010-03-01', 1, 1)")
    conn.commit()
    fm = _frontmatter(mirror.render_thread(conn, 991))
    assert fm["aliases"] == ["2010/03/13 --- ТАНКОДРОМ НИИ 21"]
    assert fm["tid"] == 991


def test_frontmatter_survives_yaml_special_chars_in_author(tmp_path):
    conn = db.connect(tmp_path / "t5.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    for tid, author in ((996, "!gryk"), (995, "[68]Father"), (994, "|Bot|")):
        conn.execute(
            "INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
            "VALUES (?, 19, 'Заголовок: с двоеточием и \"кавычкой\"', ?, '2007-04-02', 1, 1)",
            (tid, author))
    conn.commit()
    for tid, author in ((996, "!gryk"), (995, "[68]Father"), (994, "|Bot|")):
        fm = _frontmatter(mirror.render_thread(conn, tid))
        assert fm["автор"] == author
        assert fm["aliases"] == ['Заголовок: с двоеточием и "кавычкой"']


def test_bbcode_leak_with_double_brackets_is_not_a_wikilink(tmp_path):
    conn = db.connect(tmp_path / "t7.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Типовые вопросы о Субару')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (992, 19, 'Тема с мусором', 'DTR', '2007-04-02', 1, 1)")
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (53500, 992, 1, 'DTR', '2007-04-02 12:04:04', '#1', "
                 "'фото тут [[IMG]http://example.com/x.jpg[/img]', 'фото тут')")
    conn.commit()
    md = mirror.render_thread(conn, 992)
    assert "[[IMG]" not in md
    assert "\\[\\[IMG]" in md
    assert "##### Пост 53500" in md


def test_all_generated_frontmatter_parses_as_yaml(tmp_path):
    conn = db.connect(tmp_path / "t6.sqlite"); db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Раздел: с \"кавычкой\"')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (993, 19, '215\\60 R16 ''RUS'' SUBaruZERO', '''RUS'' SUBaruZERO', "
                 "'2007-04-02', NULL, 1)")
    conn.commit()
    fm = _frontmatter(mirror.render_thread(conn, 993))
    assert fm["автор"] == "'RUS' SUBaruZERO"
    assert fm["раздел"] == 'Раздел: с "кавычкой"'
    assert fm["aliases"] == ["215\\60 R16 'RUS' SUBaruZERO"]


def test_write_all_refuses_to_wipe_a_mirror_it_cannot_explain(tmp_path):
    # Дефект, пришедший вместе с точкой входа: `run mirror` с пустой (или не
    # той) базой создавал базу на лету, write_all писал 0 заметок и подчищал
    # ВСЕ существующие как осиротевшие — 6338 заметок исчезали, а конвейер
    # рапортовал об успехе. Предохранитель: удалений не может быть больше,
    # чем записей.
    import pytest
    out = tmp_path / "Источники"
    conn = _seed(tmp_path)
    mirror.write_all(conn, out)
    before = sorted(p.name for p in out.glob("*.md"))

    empty = db.connect(tmp_path / "empty.sqlite"); db.init_schema(empty)
    with pytest.raises(RuntimeError) as e:
        mirror.write_all(empty, out)
    assert "0" in str(e.value)
    assert sorted(p.name for p in out.glob("*.md")) == before, "заметки должны остаться на месте"


def test_write_all_refuses_when_deletions_outnumber_writes(tmp_path):
    # Тот же класс ошибки без пустой базы: опечатка в `--db` привела на
    # маленькую/чужую базу. Пишем 1 заметку, удалили бы 5 — это не уборка
    # мусора, это «база не описывает это зеркало».
    import pytest
    out = tmp_path / "Источники"
    out.mkdir(parents=True)
    for tid in (101, 102, 103, 104, 105):
        (out / ("Тема %d.md" % tid)).write_text("старое зеркало", encoding="utf-8")
    conn = _seed(tmp_path)
    with pytest.raises(RuntimeError):
        mirror.write_all(conn, out)
    # чужие заметки на месте (запись новых при этом не отменяется — она
    # не разрушительна, отменяется только уборка)
    assert all((out / ("Тема %d.md" % tid)).exists() for tid in (101, 102, 103, 104, 105))


def test_safeguard_does_not_block_normal_orphan_cleanup(tmp_path):
    # Предохранитель не должен убить полезное поведение: одна осиротевшая
    # заметка при 1 записанной — удаляется.
    out = tmp_path / "Источники"
    conn = _seed(tmp_path)
    mirror.write_all(conn, out)
    (out / "Тема 777.md").write_text("осталось от прошлого прогона", encoding="utf-8")
    mirror.write_all(conn, out)
    assert not (out / "Тема 777.md").exists()
    assert (out / "Тема 10045.md").exists()
