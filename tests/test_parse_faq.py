from pathlib import Path

from pipeline import parse_faq

FIX = Path(__file__).parent / "fixtures"


def _html(name: str) -> str:
    return (FIX / name).read_bytes().decode("cp1251", "replace")


def test_parses_bitrix_entry():
    entry = parse_faq.parse(_html("faq_element_bitrix.html"))
    assert entry is not None
    assert entry.engine == "bitrix"
    assert entry.nr == 10
    assert entry.catnr is None
    assert entry.question == "Процедура осмотра подкапотного пространства."
    assert "Осведомляемся о своевременности замены фильтров" in entry.answer_md
    # Служебные куски catalog-element не должны просочиться в ответ.
    assert "Назад в раздел" not in entry.answer_md
    assert entry.prog == "Субару - покупаем."
    assert "На что обращать внимание при выборе Subaru?" in entry.category
    assert entry.images == []


def test_parses_old_engine_entry():
    entry = parse_faq.parse(_html("faq_old_table.html"))
    assert entry is not None
    assert entry.engine == "old"
    assert entry.nr == 11
    assert entry.catnr == 1
    assert entry.prog == "COMMON"
    assert entry.question == "Чем отличаются Legacy и Outback ?"
    assert "Legacy Outback - одна из комплектаций" in entry.answer_md
    assert "Общая информация о Субару" in entry.category


def test_bitrix_entry_with_images_gets_absolute_urls():
    entry = parse_faq.parse(_html("faq_element_bitrix_images.html"))
    assert entry is not None
    assert entry.nr == 502
    assert len(entry.images) == 28
    assert all(u.startswith("http://www.subaru-faq.ru/upload/blog/") for u in entry.images)


def test_images_in_answer_md_use_the_same_absolute_url_as_entry_images():
    # Регрессия: html_text.to_markdown кладёт в `![](url)` СЫРОЙ (относительный)
    # адрес из HTML, а entry.images абсолютизирован через urljoin — если их не
    # свести к одной форме, pipeline.mirror.render_post_body ищет картинку в
    # тексте по одному URL, а находит её в словаре по другому: каждая реально
    # найденная картинка превращается разом и в "потерянную" в тексте, и в
    # "сироту" в конце заметки (найдено на живом корпусе, FAQ 502).
    entry = parse_faq.parse(_html("faq_element_bitrix_images.html"))
    assert entry is not None
    for url in entry.images:
        assert ("![](%s)" % url) in entry.answer_md
    assert "../upload/blog/" not in entry.answer_md


def test_bitrix_id_falls_back_to_backurl_when_print_link_absent():
    # ELEMENT_ID=377 со служебными query-декорациями (clear_cache) — снимок
    # без верхнего меню, значит без ссылки "печать" рядом с ELEMENT_ID=N.
    # Хидден-поле backurl формы логина несёт тот же номер и переживает даже
    # такой урезанный снимок (см. разведку задачи 6).
    entry = parse_faq.parse(_html("faq_element_bitrix_no_printlink.html"))
    assert entry is not None
    assert entry.nr == 377


def test_section_listing_page_has_no_answer():
    # div.catalog-section-list — категория, не отдельный вопрос-ответ.
    assert parse_faq.parse(_html("faq_section_listing.html")) is None


def test_unrelated_page_yields_none():
    assert parse_faq.parse(_html("broken_db_error.html")) is None


def test_bitrix_embedded_question_promoted_over_mismatched_title():
    # Дефект, найденный лидом на живом корпусе (FAQ 103): часть страниц
    # Bitrix несёт в теле catalog-element СВОЙ дублирующий "Вопрос:"/"Ответ:"
    # (миграция из старого движка вставила текст целиком), и заголовок h1 —
    # НЕ сам вопрос, а название темы раздела. Настоящий вопрос — из тела,
    # заголовок уходит в `title` (алиас), метки и дублированный текст вопроса
    # не должны оставаться в ответе.
    entry = parse_faq.parse(_html("faq_element_bitrix_embedded_qa_mismatch.html"))
    assert entry is not None
    assert entry.question == "Не вредно ли на машине с АКПП буксировать прицеп?"
    assert entry.title == "Рекомендации по использованию прицепов на автомобилях с АКПП"
    assert "Вопрос:" not in entry.answer_md
    assert "Ответ:" not in entry.answer_md
    assert entry.answer_md.startswith("На автомобилях с АКПП допускается")
    # Сам вопрос не должен повторяться внутри ответа.
    assert "Не вредно ли на машине с АКПП" not in entry.answer_md


def test_bitrix_answer_label_only_is_stripped_without_touching_title():
    # У части записей в теле только метка "Ответ:" без дублированного
    # вопроса — заголовок h1 уже несёт настоящий вопрос, трогать question
    # не нужно, только убрать служебную метку.
    entry = parse_faq.parse(_html("faq_element_bitrix_answer_label_only.html"))
    assert entry is not None
    assert entry.question == "Замена шлангов ГУР своими руками"
    assert entry.title is None
    assert "Ответ:" not in entry.answer_md
    assert entry.answer_md.startswith("Если шланги гидроусилителя")


def test_bitrix_entry_without_markers_has_no_title():
    # Регрессия: у записей без дублирующих меток `title` должен остаться
    # `None`, а не что-то унаследованное от предыдущего разбора.
    entry = parse_faq.parse(_html("faq_element_bitrix.html"))
    assert entry is not None
    assert entry.title is None
