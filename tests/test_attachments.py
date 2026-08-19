from pipeline import attachments


def test_forum_chrome_is_its_own_kind():
    # Смайлы и иконки движка — не контент поста и не то, что фаза добора
    # должна качать: у них никогда не было собственного файла.
    assert attachments.classify("/bitrix/images/forum/smile/icon_smile.gif") == "chrome"
    assert attachments.classify("images/smiley_icons/icon_smile.gif") == "chrome"


def test_getfile_and_show_file_are_content_not_chrome():
    # 253 getfile + 85 show_file + 7 thumbnails — реальные вложения форума,
    # их Ф2 обязана увидеть (см. Ruling 23).
    assert attachments.classify("/index.php?t=getfile&id=1234") == "local"
    assert attachments.classify(
        "http://subaru-faq.ru/bitrix/components/bitrix/forum.interface/show_file.php?fid=1"
    ) == "local"
    assert attachments.classify("/upload/WEB-002/thumbnails/x.jpg") == "local"


def test_foreign_host_is_external_even_with_chrome_looking_path():
    # Правило хрома действует только для своих адресов: чужой хост с путём
    # bitrix/images — всё равно внешняя картинка, её качают из веба.
    assert attachments.classify("http://dead.host/x.jpg") == "external_image"
    assert attachments.classify("//other.host/bitrix/images/x.gif") == "external_image"


def test_status_marks_content_pending_and_chrome_skip():
    # I4: контентное вложение без файла обязано быть pending, иначе фаза
    # добора (WHERE status='pending') молча пропустит 348 своих вложений.
    assert attachments.initial_status("local") == "pending"
    assert attachments.initial_status("external_image") == "pending"
    assert attachments.initial_status("chrome") == "skip"


def test_is_content_is_the_single_rule_for_rendering_and_fetching():
    assert attachments.is_content("local") and attachments.is_content("external_image")
    assert not attachments.is_content("chrome")
