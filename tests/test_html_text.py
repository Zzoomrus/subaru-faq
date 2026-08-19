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
