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
