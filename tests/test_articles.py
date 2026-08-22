import json

import pytest

from pipeline import articles


def _fact(fid, **extra):
    d = {"источник": "Тема 42335#Пост 248484", "цитата": "цитата факта %s" % fid,
         "суть": "суть", "id": fid}
    d.update(extra)
    return d


def _write_inputs(tmp_path, key, frontmatter_lines, body="Текст[^f1].\n", verified=None):
    """Пишет `<tmp_path>/articles/черновики/<key>.md` (frontmatter из
    `frontmatter_lines` + `body`) и `<tmp_path>/articles/проверено/<key>.json`
    (`verified`, по умолчанию один факт `f1`) — минимальная пара входов для
    `articles.build`, без лишних деталей пилотного `_write_pilot`."""
    (tmp_path / "articles" / "черновики").mkdir(parents=True, exist_ok=True)
    (tmp_path / "articles" / "проверено").mkdir(parents=True, exist_ok=True)
    draft = "---\n" + "\n".join(frontmatter_lines) + "\n---\n\n" + body
    (tmp_path / "articles" / "черновики" / ("%s.md" % key)).write_text(draft, encoding="utf-8")
    verified = verified if verified is not None else [_fact("f1")]
    (tmp_path / "articles" / "проверено" / ("%s.json" % key)).write_text(
        json.dumps({"проверено": verified, "отброшено": [], "статистика": {}}, ensure_ascii=False),
        encoding="utf-8")


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


# --- ревью задачи 5: F1 — запрет на самописную сноску держался только на
# нулевом отступе, пробел/таб/`> ` его снимали -------------------------------


@pytest.mark.parametrize("prefix", ["", " ", "   ", "\t", "> ", "> > "])
def test_embedded_definition_is_rejected_at_any_indentation(prefix):
    """Ревью нашло: `^\\[\\^...\\]:` без `[ \\t>]*` перед собой отбивал только
    колонку 0 — один ведущий пробел, табуляция или обёртка `> ` защиту снимали
    целиком. Хуже всего на FAQ, где код по контракту не даёт подписи вовсе:
    протащенная строка выдумывает и автора, и дату."""
    draft = ("Диаметр[^f1].\n\n%s[^f1]: «это 4,75 мм» — ЧужойАвтор, 01.01.2000, "
              "[[FAQ 100#Ответ]]\n") % prefix
    verified = [{"id": "f1", "источник": "FAQ 100#Ответ", "цитата": "это 4,75 мм", "суть": "д"}]
    with pytest.raises(articles.DraftError):
        articles.render(draft, verified, {"заголовок": "Х"})


def test_embedded_definition_with_crlf_is_rejected():
    draft = ("Диаметр[^f1].\r\n\r\n [^f1]: «это 4,75 мм» — Чужой, 01.01.2000, "
              "[[FAQ 100#Ответ]]\r\n")
    verified = [{"id": "f1", "источник": "FAQ 100#Ответ", "цитата": "это 4,75 мм", "суть": "д"}]
    with pytest.raises(articles.DraftError):
        articles.render(draft, verified, {"заголовок": "Х"})


# --- ревью задачи 5: F2 — многострочная (законная по канону) цитата рвала
# сноску: подпись и ссылка вываливались за пределы определения -------------


def test_multiline_quote_does_not_break_out_of_the_footnote_definition():
    """Дословность цитаты сверяется по `notes.normalize_spaces` (перенос
    строки в заметке — не подделка, Global Constraint №1), значит цитата,
    законно прошедшая проход 1, может содержать `\\n`. Сноска обязана
    остаться ОДНОЙ строкой определения, а не оборваться на первом переносе,
    оставив автора/дату/ссылку вне `[^f1]: ...`."""
    draft = "Диаметр трубки[^f1]."
    verified = [{"id": "f1", "источник": "Тема 1#Пост 100",
                 "цитата": "Трубки нужны 3/16 дюйма,\nэто   4,75 мм", "суть": "диаметр",
                 "автор": "Razum", "дата": "11.10.2014"}]
    out = articles.render(draft, verified, {"заголовок": "Х"})
    assert ("[^f1]: «Трубки нужны 3/16 дюйма, это 4,75 мм» — Razum, 11.10.2014, "
            "[[Тема 1#Пост 100]]") in out
    # Ни автор, ни ссылка не должны оказаться на отдельной, ничем не
    # предваряемой строке вне определения сноски.
    for line in out.splitlines():
        assert not line.startswith("это")
        assert not line.startswith("Razum")


# --- ревью задачи 5: F3 — `путь`/`заголовок` из черновика ИИ писали файл
# куда угодно (обход каталога, абсолютный путь, слэш в заголовке) -----------


def test_build_rejects_directory_traversal_in_путь(tmp_path):
    _write_inputs(tmp_path, "х", ["заголовок: Взлом", "путь: ../../../../tmp/sf-escape"])
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


def test_build_rejects_absolute_путь(tmp_path):
    _write_inputs(tmp_path, "х", ["заголовок: Х", "путь: /tmp/sf-escape-abs"])
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


def test_build_rejects_slash_in_заголовок(tmp_path):
    """Слэш в заголовке статьи про Subaru напрашивается сам («Ремонт
    EJ20/EJ25», «3/16 дюйма») — обязан дать внятный `DraftError`, а не
    `FileNotFoundError` из недр `pathlib`."""
    _write_inputs(tmp_path, "х", ["заголовок: Ремонт EJ20/EJ25", "путь: Двигатель"])
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


def test_build_rejects_dotdot_путь_without_slash(tmp_path):
    _write_inputs(tmp_path, "х", ["заголовок: Х", "путь: .."])
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


# --- ревью задачи 5: F4 — маркер в коде/HTML-комментарии считался
# «использованным», обнуляя замер непроцитированных источников -------------


def test_marker_inside_fenced_code_html_comment_or_inline_code_is_not_used():
    draft = ("Полностью недоказанное утверждение: масло менять раз в 5 тыс. км.\n\n"
              "<!-- [^f1] -->\n\n```\n[^f2]\n```\n\nи `[^f3]` в инлайн-коде.\n")
    assert articles.used_ids(draft) == []
    out = articles.render(draft, [_fact("f1"), _fact("f2"), _fact("f3")], {"заголовок": "Х"})
    assert "неиспользованные_факты: [f1, f2, f3]" in out
    assert "## Сноски" not in out          # ни одна из скрытых ссылок не отрендерена


def test_marker_in_ordinary_prose_next_to_code_span_is_still_used():
    """Вырезание кода не должно случайно съедать настоящие маркеры рядом с
    ним."""
    draft = "Диаметр `4,75 мм` трубки[^f1]."
    out = articles.render(draft, [_fact("f1")], {"заголовок": "Х"})
    assert "## Сноски" in out
    assert "неиспользованные_факты" not in out


# --- ревью задачи 5: F5 — `собрано: date.today()` ломает побитовую
# пересборку (Global Constraint №8) -----------------------------------------


def test_собрано_is_omitted_not_defaulted_to_todays_date_when_absent():
    out1 = articles.render("Текст[^f1].", [_fact("f1")], {"заголовок": "Х"})
    out2 = articles.render("Текст[^f1].", [_fact("f1")], {"заголовок": "Х"})
    assert out1 == out2
    assert "собрано:" not in out1


def test_собрано_uses_explicit_meta_value_when_given():
    out = articles.render("Текст[^f1].", [_fact("f1")], {"заголовок": "Х", "собрано": "2026-08-21"})
    assert "собрано: 2026-08-21" in out


def test_build_stamps_собрано_deterministically_and_rebuild_is_byte_identical(tmp_path):
    """`build` обязан подставить `собрано` сам (не полагаясь на
    `date.today()` внутри `render`), и повторная сборка БЕЗ изменения
    черновика — байт-в-байт то же самое (Global Constraint №8)."""
    _write_inputs(tmp_path, "х", ["заголовок: Х", "путь: Узел"])
    out_path = articles.build("х", tmp_path)
    text = out_path.read_text(encoding="utf-8")
    assert "собрано:" in text
    out_path2 = articles.build("х", tmp_path)
    assert out_path2.read_text(encoding="utf-8") == text


# --- ревью задачи 5: F6 — «источников» считал факты, а не источники --------


def test_источников_counts_distinct_sources_not_facts():
    verified = [
        {"id": "f1", "источник": "Тема 1#Пост 1", "цитата": "а", "суть": "х"},
        {"id": "f2", "источник": "Тема 1#Пост 1", "цитата": "б", "суть": "х"},
        {"id": "f3", "источник": "Тема 1#Пост 2", "цитата": "в", "суть": "х"},
    ]
    out = articles.render("Т[^f1][^f2][^f3].", verified, {"заголовок": "Х"})
    assert "источников: 2" in out
