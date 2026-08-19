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
