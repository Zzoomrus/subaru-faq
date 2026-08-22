import json

import pytest

from pipeline import articles


def _fact(fid, **extra):
    d = {"источник": "Тема 42335#Пост 248484", "цитата": "цитата факта %s" % fid,
         "суть": "суть", "id": fid}
    d.update(extra)
    return d


# --- сноску рендерит код, а не ИИ ------------------------------------------


def test_footnote_is_rendered_by_code_not_by_ai():
    """Маркер ставит ИИ, содержимое сноски — код.

    Если бы сноску набирал ИИ, он мог бы написать правильную цитату при
    неправильной ссылке — и проверка сошлась бы на цитате.
    """
    draft = "Диаметр трубки — 4,75 мм[^f1]."
    verified = [{"id": "f1", "источник": "Тема 42335#Пост 248484",
                 "цитата": "это 4,75 мм", "суть": "диаметр",
                 "автор": "Razum", "дата": "11.10.2014"}]
    out = articles.render(draft, verified, {"заголовок": "Тормозные трубки"})
    assert "[^f1]: «это 4,75 мм» — Razum, 11.10.2014, [[Тема 42335#Пост 248484]]" in out


def test_footnote_without_author_or_date_is_the_faq_form():
    """У записей FAQ нет автора-человека и нет настоящей даты написания —
    только момент, когда страницу снял краулер. Подставлять его как «дату»
    было бы обманом того же рода, против которого затеян проект: второй вид
    сноски просто не несёт подписи вовсе (спека §5, правка бригадира)."""
    draft = "Раз в 30 тысяч км[^f1]."
    verified = [{"id": "f1", "источник": "FAQ 42#Ответ",
                 "цитата": "Раз в 30 тысяч км", "суть": "интервал"}]
    out = articles.render(draft, verified, {"заголовок": "Замена колодок"})
    assert "[^f1]: «Раз в 30 тысяч км» — [[FAQ 42#Ответ]]" in out


def test_footnote_treats_missing_and_empty_author_date_the_same():
    """`facts.check_all` без базы не добавляет ключи вовсе, а FAQ-факт с
    базой под рукой получает `автор: None, дата: None` — оба случая обязаны
    дать один и тот же безподписной вид сноски, а не разные."""
    draft = "Утверждение[^f1]."
    verified_absent = [{"id": "f1", "источник": "FAQ 1#Ответ", "цитата": "утверждение", "суть": "х"}]
    verified_none = [{"id": "f1", "источник": "FAQ 1#Ответ", "цитата": "утверждение", "суть": "х",
                       "автор": None, "дата": None}]
    verified_empty = [{"id": "f1", "источник": "FAQ 1#Ответ", "цитата": "утверждение", "суть": "х",
                        "автор": "", "дата": ""}]
    out_absent = articles.render(draft, verified_absent, {"заголовок": "Х"})
    out_none = articles.render(draft, verified_none, {"заголовок": "Х"})
    out_empty = articles.render(draft, verified_empty, {"заголовок": "Х"})
    line = "[^f1]: «утверждение» — [[FAQ 1#Ответ]]"
    assert line in out_absent
    assert line in out_none
    assert line in out_empty


def test_footnote_with_author_but_no_date():
    """Частичная атрибуция (например, `threads.started_at` не заполнен у
    части тем) не должна давать ни ошибку, ни выдуманную дату."""
    draft = "Утверждение[^f1]."
    verified = [{"id": "f1", "источник": "Тема 1#Пост 1", "цитата": "утверждение", "суть": "х",
                 "автор": "Основатель", "дата": None}]
    out = articles.render(draft, verified, {"заголовок": "Х"})
    assert "[^f1]: «утверждение» — Основатель, [[Тема 1#Пост 1]]" in out


# --- маркер без факта, факт без маркера — не молчать -----------------------


def test_marker_without_verified_fact_is_an_error():
    """Проза сослалась на факт, которого нет среди проверенных."""
    with pytest.raises(articles.DraftError) as e:
        articles.render("Утверждение[^f9].", [], {"заголовок": "Х"})
    assert "f9" in str(e.value)


def test_unused_fact_is_reported_not_silently_dropped():
    """Неиспользованный факт — сигнал, что ИИ проигнорировал источник.

    Спека §6 требует мерить, что ИИ молча не заметил; молчаливое
    выбрасывание превратило бы этот замер в ноль.
    """
    out = articles.render("Текст[^f1].", [_fact("f1"), _fact("f2")], {"заголовок": "Х"})
    assert "не использованы: f2" in out          # в frontmatter, поле `неиспользованные_факты`
    assert "неиспользованные_факты: [f2]" in out


def test_no_unused_facts_field_is_omitted_when_everything_is_used():
    out = articles.render("Текст[^f1].", [_fact("f1")], {"заголовок": "Х"})
    assert "неиспользованные_факты" not in out
    assert "не использованы" not in out


def test_every_footnote_definition_appears_once():
    draft = "Раз[^f1]. Два[^f1]. Три[^f2]."
    out = articles.render(draft, [_fact("f1"), _fact("f2")], {"заголовок": "Х"})
    assert out.count("[^f1]: ") == 1
    assert out.count("[^f2]: ") == 1


def test_ai_cannot_fake_a_footnote_by_typing_its_own_definition():
    """Главная дыра, которую задача обязана закрыть: если бы ИИ мог сам
    вписать строку определения сноски, он мог бы подписать верную цитату
    чужим именем — и ни `render`, ни `verify.py` (у него нет проверки
    автора/даты против базы) это не поймали бы. Черновик с готовым
    определением отбраковывается целиком, а не молча перезаписывается."""
    draft = ("Диаметр трубки — 4,75 мм[^f1].\n\n"
             "[^f1]: «это 4,75 мм» — ЧужойАвтор, 01.01.2000, [[Тема 42335#Пост 248484]]\n")
    verified = [{"id": "f1", "источник": "Тема 42335#Пост 248484",
                 "цитата": "это 4,75 мм", "суть": "диаметр",
                 "автор": "Razum", "дата": "11.10.2014"}]
    with pytest.raises(articles.DraftError):
        articles.render(draft, verified, {"заголовок": "Х"})


# --- used_ids ---------------------------------------------------------------


def test_used_ids_deduplicates_preserving_first_appearance_order():
    assert articles.used_ids("Раз[^f2]. Два[^f1]. Три[^f2].") == ["f2", "f1"]


def test_used_ids_empty_draft_has_no_markers():
    assert articles.used_ids("Просто текст без сносок.") == []


# --- frontmatter: узел/модель/источников/собрано ----------------------------


def test_frontmatter_carries_node_and_model_tags():
    out = articles.render("Текст[^f1].", [_fact("f1")],
                           {"заголовок": "Х", "узел": "тормоза", "модель": ["bc-bj", "gc8"]})
    assert "узел: тормоза" in out
    assert "модель: [bc-bj, gc8]" in out


def test_frontmatter_counts_sources():
    out = articles.render("Текст[^f1][^f2].", [_fact("f1"), _fact("f2")], {"заголовок": "Х"})
    assert "источников: 2" in out


# --- build: собирает готовую заметку из черновика + проверенных фактов -----


DRAFT_WITH_META = """---
заголовок: Тормозные трубки
узел: тормоза
путь: Тормоза
модель: [bc-bj, gc8]
---

Диаметр трубки — 4,75 мм[^f1].
"""


def _write_pilot(tmp_path):
    (tmp_path / "articles" / "черновики").mkdir(parents=True)
    (tmp_path / "articles" / "проверено").mkdir(parents=True)
    (tmp_path / "articles" / "черновики" / "тормоза.md").write_text(DRAFT_WITH_META, encoding="utf-8")
    verified = {"проверено": [{"id": "f1", "источник": "Тема 42335#Пост 248484",
                                "цитата": "это 4,75 мм", "суть": "диаметр",
                                "автор": "Razum", "дата": "11.10.2014"}],
                "отброшено": [], "статистика": {"всего": 1, "прошло": 1, "отброшено": 0}}
    (tmp_path / "articles" / "проверено" / "тормоза.json").write_text(
        json.dumps(verified, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_build_writes_article_under_wiki_stati_by_node_path(tmp_path):
    root = _write_pilot(tmp_path)
    out_path = articles.build("тормоза", root)
    assert out_path == root / "wiki" / "Статьи" / "Тормоза" / "Тормозные трубки.md"
    text = out_path.read_text(encoding="utf-8")
    assert "[^f1]: «это 4,75 мм» — Razum, 11.10.2014, [[Тема 42335#Пост 248484]]" in text
    assert "узел: тормоза" in text


def test_build_missing_draft_is_a_clear_error(tmp_path):
    (tmp_path / "articles" / "проверено").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        articles.build("нет-такого", tmp_path)


def test_build_missing_verified_facts_is_a_clear_error(tmp_path):
    (tmp_path / "articles" / "черновики").mkdir(parents=True)
    (tmp_path / "articles" / "черновики" / "х.md").write_text(DRAFT_WITH_META, encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        articles.build("х", tmp_path)


def test_build_requires_explicit_target_path_in_frontmatter(tmp_path):
    """`путь` — это папка `wiki/Статьи/<путь>/`. Код не угадывает её из
    `узел` (капитализация акронимов вроде «ГРМ» не выводится правилом без
    исключений, а тихое неверное угадывание — ровно тот класс ошибки,
    против которого затеяна вся проверка)."""
    (tmp_path / "articles" / "черновики").mkdir(parents=True)
    (tmp_path / "articles" / "проверено").mkdir(parents=True)
    draft = "---\nзаголовок: Х\nузел: тормоза\n---\n\nТекст[^f1].\n"
    (tmp_path / "articles" / "черновики" / "х.md").write_text(draft, encoding="utf-8")
    verified = {"проверено": [_fact("f1")], "отброшено": [], "статистика": {}}
    (tmp_path / "articles" / "проверено" / "х.json").write_text(
        json.dumps(verified, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)
