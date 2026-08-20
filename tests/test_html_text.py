from pipeline import html_text


def test_quote_becomes_blockquote():
    html = ("<table class='forum-quote'><thead><tr><th>Цитата</th></tr></thead>"
            "<tbody><tr><td>Turanku пишет: <br />К монастырю, да?</td></tr></tbody></table>"
            " <br />ага к 21-00")
    md = html_text.to_markdown(html)
    assert "> Turanku пишет:" in md
    assert "> К монастырю, да?" in md
    assert md.rstrip().endswith("ага к 21-00")


def test_image_prefers_full_size_from_data_bx_src():
    html = ('<img src="https://host/thumb_m.jpg" data-bx-viewer="image" '
            'data-bx-src="https://host/full.jpg" />')
    assert html_text.images(html) == ["https://host/full.jpg"]


def test_br_becomes_newline_and_entities_decoded():
    assert html_text.plain_text("а&nbsp;б<br />в") == "а б\nв"


def test_link_kept_as_markdown():
    html = '<a href="http://example.com/x" target="_blank">пример</a>'
    assert html_text.to_markdown(html) == "[пример](http://example.com/x)"


def test_script_does_not_leak_into_text():
    # Реальный случай из архива: video-embed вставляет <script> с конфигом
    # jwplayer прямо в тело поста — его содержимое не должно попадать в текст.
    html = "текст до<script>window.x = {'file':'http://y/z.mp4'};</script>текст после"
    assert html_text.to_markdown(html) == "текст дотекст после"


def test_noscript_fallback_does_not_leak_into_text():
    html = "видео <noscript>В вашем браузере отключен JavaScript</noscript>тут"
    assert html_text.to_markdown(html) == "видео тут"


def test_image_wrapped_in_link_stays_an_image():
    # Реальный паттерн из архива: лайтбокс-ссылка на страницу хостинга
    # картинок (radikal.ru, qip.ru) без подписи — оборачивает превью.
    # Ссылка ведёт на HTML-страницу, а не на файл, поэтому картинку нужно
    # рендерить как картинку, а не превращать в голый URL текстом.
    html = '<a href="http://radikal.ru/page.jpg.html"><img src="http://s.radikal.ru/thumb.jpg" /></a>'
    assert html_text.to_markdown(html) == "![](http://s.radikal.ru/thumb.jpg)"


def test_nested_quote_plain_text_strips_all_quote_markers():
    # Ответ на цитату внутри чужой цитаты — частый паттерн на форуме.
    # to_markdown корректно даёт двухуровневую разметку "> > текст",
    # но plain_text должна снять ВСЕ уровни "> ", не оставляя ни одного
    # хвостового ">", при этом не теряя текст ни одной из цитат.
    html = (
        "<table class='forum-quote'><thead><tr><th>Цитата</th></tr></thead>"
        "<tbody><tr><td>Manur пишет: "
        "<table class='forum-quote'><thead><tr><th>Цитата</th></tr></thead>"
        "<tbody><tr><td>crazy_digger пишет: <br />Резинку зажевал"
        "</td></tr></tbody></table>"
        " ответ на цитату</td></tr></tbody></table>"
        " основной текст"
    )
    pt = html_text.plain_text(html)
    assert ">" not in pt
    assert "Manur пишет:" in pt
    assert "crazy_digger пишет:" in pt
    assert "Резинку зажевал" in pt
    assert "ответ на цитату" in pt
    assert pt.rstrip().endswith("основной текст")


def test_link_with_parenthesis_in_url_plain_text():
    # Реальный случай из архива: URL со скобками (страница вида page(1).html).
    # Наивный "жадный до первой закрывающей скобки" разбор ссылки в
    # plain_text обрезает URL по первой ")" внутри самого адреса и оставляет
    # хвост URL как текст.
    html = '<a href="http://example.com/page(1).html">ссылка</a> текст'
    assert html_text.plain_text(html) == "ссылка текст"


def test_plain_text_is_derived_from_markdown_not_from_html_again():
    # Тело поста разбиралось трижды (to_markdown, plain_text -> ещё раз
    # to_markdown, images). Теперь plain_text — чистая функция от уже
    # посчитанного markdown, и parse_thread считает markdown один раз.
    html = ('<table class="forum-quote"><tr><td>Вася пишет:<br>привет</td></tr></table>'
            'ответ <a href="http://example.com/x">тут</a> '
            '<img src="/bitrix/images/smile.gif">')
    md = html_text.to_markdown(html)
    assert html_text.plain_text_from_markdown(md) == html_text.plain_text(html)
    assert "> Вася пишет:" in md
    assert "> " not in html_text.plain_text_from_markdown(md)


def test_legacy_quote_without_forum_quote_class_becomes_blockquote():
    # Старый (пре-Bitrix) формат цитаты: таблица без класса `forum-quote`,
    # где атрибуция лежит в `td.SmallText`, а тело цитаты — в `td.quote`.
    # Отложенная находка №3 ревью: пока тело заметки было плоским текстом,
    # эти посты были неотличимы от остальных; с переходом на markdown они
    # остались бы единственными, где цитата не отделена от слов автора.
    # На корпусе таких постов 877 в 131 теме.
    html = ('<table align="center" width="90%"><tr><td class="SmallText">'
            '<b>Nikon писал(а) Птн, 09 Января 2004 07:38</b></td></tr>'
            '<tr><td class="quote"><br/>1. Ломучесть<br/>2. Шумность<br/></td></tr></table>'
            '<br/>Ник у тебя хороший')
    md = html_text.to_markdown(html)
    assert "> Nikon писал(а) Птн, 09 Января 2004 07:38" in md
    assert "> 1. Ломучесть" in md
    assert "> 2. Шумность" in md
    # ответ автора поста цитатой НЕ становится
    assert "\nНик у тебя хороший" in md


def test_nested_legacy_quote_gets_second_level_of_markers():
    # Цитата внутри цитаты (204 случая на корпусе) — вложенность видна
    # уровнями `> >`, как и у формата Bitrix.
    html = ('<table><tr><td class="SmallText"><b>Внешний писал(а)</b></td></tr>'
            '<tr><td class="quote">'
            '<table><tr><td class="SmallText"><b>Внутренний писал(а)</b></td></tr>'
            '<tr><td class="quote">исходный вопрос</td></tr></table>'
            '<br/>мой ответ на вопрос</td></tr></table>')
    md = html_text.to_markdown(html)
    assert "> > исходный вопрос" in md
    assert "> мой ответ на вопрос" in md


def test_layout_table_without_quote_cell_is_not_quoted():
    # Обычная табличка в посте (не цитата) остаётся обычным текстом.
    html = '<table><tr><td>слева</td><td>справа</td></tr></table>'
    assert "> " not in html_text.to_markdown(html)


def test_html_comments_do_not_leak_into_markdown():
    # Дефект, найденный при ревизии задачи 6 (FAQ): `<!-- -->` — это
    # `bs4.Comment`, а `Comment` — ПОДКЛАСС `NavigableString`, так что без
    # явной проверки текст комментария рендерится как обычный текст поста.
    # На живом корпусе FAQ это оставляло видимый мусор "SPCode Start"/"SPCode
    # End" (редакторские маркеры старого WYSIWYG) в 23 из 174 заметок —
    # см. task-6-report.md.
    md = html_text.to_markdown("до<!-- SPCode Start -->между<!-- SPCode End -->после")
    assert "SPCode" not in md
    assert md == "домеждупосле"
