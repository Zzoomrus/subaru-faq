from pathlib import Path

from pipeline import parse_thread

FIX = Path(__file__).parent / "fixtures"


def _html(name: str) -> str:
    return (FIX / name).read_bytes().decode("cp1251", "replace")


def test_parses_posts_with_author_and_date():
    page = parse_thread.parse(_html("read_19_10045_1.html"))
    assert page.title == "Параметры коробок и редукторов Субару"
    first = page.posts[0]
    assert first.mid == 53392
    assert first.author == "DTR"
    assert first.author_uid == 1262
    assert first.posted_at == "2007-04-02 12:04:04"
    assert first.number == "#1"


def test_signature_is_not_part_of_post_text():
    page = parse_thread.parse(_html("read_20_31559_2.html"))
    joined = "\n".join(p.text for p in page.posts)
    assert "silver WRX Bu-Bu-Bu" not in joined


def test_quote_present_in_markdown():
    page = parse_thread.parse(_html("read_20_31559_2.html"))
    quoted = [p for p in page.posts if p.mid == 245922]
    assert quoted and "> Turanku пишет:" in quoted[0].markdown


def test_broken_db_error_page_yields_no_posts():
    page = parse_thread.parse(_html("broken_db_error.html"))
    assert page.posts == []


def test_author_without_profile_link_still_captured():
    # У части постов (спам-аккаунт/удалённый пользователь) div.forum-user-name
    # не содержит <a> со ссылкой на профиль — только текст в span. Полный
    # прогон по корпусу нашёл 19 таких постов, где старая реализация теряла
    # автора (author="", author_uid=None) вместо чтения текста из div.
    page = parse_thread.parse(_html("read_16_38868_1.html"))
    post = [p for p in page.posts if p.mid == 342659][0]
    assert post.author == "mallorymercy vigorda"
    assert post.author_uid is None


def test_message_page_yields_target_post_and_title():
    # message_<FID>_<TID>_<MID>.html — та же разметка треда, что и у read_*,
    # но фокус на одном сообщении. Парсер не знает про имя файла (это забота
    # вызывающего кода/Задачи 5) — здесь просто проверяем, что структура
    # такой страницы разбирается так же корректно: пост с целевым mid из
    # имени файла присутствует среди распарсенных, а заголовок темы верный.
    page = parse_thread.parse(_html("message_1_78938_414802.html"))
    assert page.title == "Looking for best bang for buck processor. *Newbie*"
    mids = [p.mid for p in page.posts]
    assert 414802 in mids
    post = [p for p in page.posts if p.mid == 414802][0]
    assert post.author == "Joe Clark"
    assert post.author_uid == 86070
    assert post.number == "#1"


def test_message_page_behind_bot_challenge_yields_no_posts():
    # Часть message_*.html — не форумный контент, а сохранённая антибот-
    # проверка (JS-челлендж вида ctSetCookie/ctMouseData вместо реальной
    # страницы): краулер получил челлендж вместо тела форума. Полный прогон
    # нашёл 10 таких страниц среди message_* — они должны давать 0 постов,
    # а не падать и не выдавать мусорные "посты" из разметки челленджа.
    page = parse_thread.parse(_html("message_bot_challenge.html"))
    assert page.posts == []
