import json
import os

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
    """«источников» считает РАЗЛИЧНЫЕ источники, не факты (F6 ревью) — два
    факта из одного и того же поста/ответа — один источник, не два."""
    out = articles.render(
        "Текст[^f1][^f2].",
        [_fact("f1", источник="Тема 1#Пост 1"), _fact("f2", источник="Тема 2#Пост 2")],
        {"заголовок": "Х"})
    assert "источников: 2" in out


# --- build: собирает готовую заметку из черновика + проверенных фактов -----


DRAFT_WITH_META = """---
заголовок: Тормозные трубки
узел: тормоза
путь: Тормоза
модель: [bc-bj, gc8]
собрано: 2026-08-21
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


def test_build_returns_path_relative_to_root_argument_not_resolved(tmp_path):
    """R6 ре-ревью: `build()` документирован как «пишет `wiki/Статьи/<путь>/
    <заголовок>.md` от переданного `root`» — возвращаемое значение обязано
    остаться таким, даже если `root` сам оказался симлинком (например, macOS
    `/var` -> `/private/var`). Прежняя реализация строила путь от
    `root.resolve()`, и внешняя оснастка, вызывающая `relative_to(root)` или
    `root / ...`, ломалась на расхождении корней."""
    actual_root = tmp_path / "актуальный-корень"
    actual_root.mkdir()
    _write_inputs(actual_root, "х", ["заголовок: Х", "путь: Узел", "собрано: 2026-08-21"])
    root_link = tmp_path / "ссылка-на-корень"
    root_link.symlink_to(actual_root, target_is_directory=True)
    out_path = articles.build("х", root_link)
    assert out_path == root_link / "wiki" / "Статьи" / "Узел" / "Х.md"


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
# нулевом отступе (круг 1), затем на классе ведущих символов (круг 2, тоже
# пробит: 13/20 форм проходили) — рабочая защита не привязана к началу
# строки вовсе: «маркер, сразу двоеточие» --------------------------------

_FAKE_DEFINITION = "[^f1]: «это 4,75 мм» — ЧужойАвтор, 01.01.2000, [[FAQ 100#Ответ]]"
_V_F1 = [{"id": "f1", "источник": "FAQ 100#Ответ", "цитата": "это 4,75 мм", "суть": "д"}]

# Корпус форм подделки — ровно тот, которым ре-ревью пробило круг 2
# (`.superpowers/sdd/.../task-5-rereview/атака-f1.py`): привязка к началу
# строки пропускала маркеры списков, разные виды пробелов и переносы внутри
# самого определения. Ни один префикс не является защитой — держит только
# отсутствие анкоринга к началу строки вовсе.
_F1_ATTACK_DRAFTS = {
    "колонка 0": "Диаметр[^f1].\n\n" + _FAKE_DEFINITION + "\n",
    "1 пробел": "Диаметр[^f1].\n\n " + _FAKE_DEFINITION + "\n",
    "3 пробела": "Диаметр[^f1].\n\n   " + _FAKE_DEFINITION + "\n",
    "табуляция": "Диаметр[^f1].\n\n\t" + _FAKE_DEFINITION + "\n",
    "блочная цитата": "Диаметр[^f1].\n\n> " + _FAKE_DEFINITION + "\n",
    "вложенная блочная цитата": "Диаметр[^f1].\n\n>> " + _FAKE_DEFINITION + "\n",
    "цитата + отступ": "Диаметр[^f1].\n\n>  " + _FAKE_DEFINITION + "\n",
    "элемент списка -": "Диаметр[^f1].\n\n- " + _FAKE_DEFINITION + "\n",
    "элемент списка *": "Диаметр[^f1].\n\n* " + _FAKE_DEFINITION + "\n",
    "элемент списка +": "Диаметр[^f1].\n\n+ " + _FAKE_DEFINITION + "\n",
    "нумерованный список": "Диаметр[^f1].\n\n1. " + _FAKE_DEFINITION + "\n",
    "список внутри цитаты": "Диаметр[^f1].\n\n> - " + _FAKE_DEFINITION + "\n",
    "NBSP U+00A0": "Диаметр[^f1].\n\n " + _FAKE_DEFINITION + "\n",
    "узкий неразрывный U+202F": "Диаметр[^f1].\n\n " + _FAKE_DEFINITION + "\n",
    "нулевая ширина U+200B": "Диаметр[^f1].\n\n​" + _FAKE_DEFINITION + "\n",
    "идеографический пробел U+3000": "Диаметр[^f1].\n\n　" + _FAKE_DEFINITION + "\n",
    "вертикальная табуляция": "Диаметр[^f1].\n\n\v" + _FAKE_DEFINITION + "\n",
    "подача формы": "Диаметр[^f1].\n\n\f" + _FAKE_DEFINITION + "\n",
    "экранированные скобки": "Диаметр[^f1].\n\n\\[^f1\\]: «это 4,75 мм» — ЧужойАвтор, 01.01.2000\n",
    # найдено при фиксе дефекта 5 (анкоринг к началу строки вернул уязвимость
    # к экрану, но именно эта форма корпуса круга 2 всё равно отбивалась —
    # случайно, через «id содержит хвостовой \» -> «ссылка на несуществующий
    # факт», а не через саму защиту от встроенного определения; экран только
    # на ОТКРЫВАЮЩЕЙ скобке даёт id без хвостового `\` = «f1», совпадающий с
    # настоящим фактом, и проходил бы без отдельного снятия экрана):
    "экранирована только открывающая скобка": "Диаметр[^f1].\n\n\\[^f1]: «это 4,75 мм» — ЧужойАвтор, 01.01.2000\n",
    "перенос внутри определения": "Диаметр[^f1].\n\n [^f1]:\n    «это 4,75 мм» — ЧужойАвтор, 01.01.2000\n",
    "определение в конце без \\n": "Диаметр[^f1].\n\n " + _FAKE_DEFINITION,
    "CRLF + 1 пробел": "Диаметр[^f1].\r\n\r\n " + _FAKE_DEFINITION + "\r\n",
}


@pytest.mark.parametrize("label", sorted(_F1_ATTACK_DRAFTS))
def test_embedded_definition_is_rejected_for_every_attack_form(label):
    with pytest.raises(articles.DraftError):
        articles.render(_F1_ATTACK_DRAFTS[label], _V_F1, {"заголовок": "Х"})


@pytest.mark.parametrize("draft", [
    "Маркер в заголовке — # Раздел[^f1]",
    "Маркер рядом с вики-ссылкой: [^f1] [[Тема 1#Пост 1]]",
    "Событие произошло в 12:30, см. запись[^f1].",
    "Обычное предложение: вот двоеточие после слова[^f1].",
])
def test_embedded_definition_check_has_no_false_positives_on_ordinary_prose(draft):
    """Без анкоринга к началу строки регулярка обязана оставаться безопасной
    на обычной прозе — маркер сам по себе, двоеточие после обычных слов,
    время вида `12:30` не должны считаться подделкой."""
    out = articles.render(draft, _V_F1, {"заголовок": "Х"})
    assert "[^f1]: «это 4,75 мм» — [[FAQ 100#Ответ]]" in out


# --- ре-ревью задачи 5 (пилот статей, дефект 5): убрать анкоринг к началу
# строки вовсе (круг 2 -> «маркер, сразу двоеточие» без привязки) закрыло
# все 20+ форм обхода, но заодно накрыло честную прозу — маркер сноски в
# конце придаточного, за которым обычное русское двоеточие вводит
# пояснение. Живая статья («Износ двигателей», пилот статей) отказалась
# собираться именно на такой строке. Правильное правило — среднее: строка
# считается определением, только если ПЕРЕД маркером на ней нет ничего,
# кроме пробельных символов, знаков списка и угловых скобок цитаты — тогда
# обе стороны закрыты одним условием (см. докстринг `_EMBEDDED_DEFINITION`
# в `pipeline/articles.py`).

_LIVE_EXPLANATORY_COLON = (
    "…снижают расход масла увеличенным зазором — так называемой усечённой "
    "боковой поверхностью**[^f17]:** у таких поршней низкий расход "
    "объясняется минимальным контактом нагара с цилиндром[^f18]…"
)


def test_embedded_definition_check_does_not_reject_honest_explanatory_colon_after_marker():
    """Живая находка пилота статей: маркер сноски в конце придаточного, за
    которым идёт двоеточие, вводящее пояснение — обычная конструкция
    русского языка, а не подделка. Перед маркером на строке стоит текст
    самого предложения (не только пробелы/знаки списка/`>`), значит это не
    начало блока, и Obsidian такую строку определением сноски не считает
    (ей для этого нужно начало строки) — а раз не считает, подделкой она
    быть не может."""
    v = [
        {"id": "f17", "источник": "FAQ 1#Ответ", "цитата": "x", "суть": "y"},
        {"id": "f18", "источник": "FAQ 2#Ответ", "цитата": "z", "суть": "w"},
    ]
    out = articles.render(_LIVE_EXPLANATORY_COLON, v, {"заголовок": "Х"})
    assert "[^f17]: «x»" in out
    assert "[^f18]: «z»" in out


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
    _write_inputs(tmp_path, "х",
                  ["заголовок: Взлом", "путь: ../../../../tmp/sf-escape", "собрано: 2026-08-21"])
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


def test_build_rejects_absolute_путь(tmp_path):
    _write_inputs(tmp_path, "х",
                  ["заголовок: Х", "путь: /tmp/sf-escape-abs", "собрано: 2026-08-21"])
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


def test_build_rejects_slash_in_заголовок(tmp_path):
    """Слэш в заголовке статьи про Subaru напрашивается сам («Ремонт
    EJ20/EJ25», «3/16 дюйма») — обязан дать внятный `DraftError`, а не
    `FileNotFoundError` из недр `pathlib`."""
    _write_inputs(tmp_path, "х",
                  ["заголовок: Ремонт EJ20/EJ25", "путь: Двигатель", "собрано: 2026-08-21"])
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


def test_build_accepts_nested_путь_for_model_axis(tmp_path):
    """Спека §7: модельная ось — `Статьи/Модели/Leone/…`; вложенный `путь`
    из безопасных компонентов обязан собираться, а не падать как обход."""
    _write_inputs(tmp_path, "х",
                  ["заголовок: Х", "путь: Модели/Leone", "собрано: 2026-08-21"])
    out = articles.build("х", tmp_path)
    assert out == tmp_path / "wiki" / "Статьи" / "Модели" / "Leone" / "Х.md"
    assert out.exists()


def test_build_rejects_empty_component_in_nested_путь(tmp_path):
    _write_inputs(tmp_path, "х",
                  ["заголовок: Х", "путь: Модели//Leone", "собрано: 2026-08-21"])
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


def test_build_rejects_dotdot_путь_without_slash(tmp_path):
    _write_inputs(tmp_path, "х", ["заголовок: Х", "путь: ..", "собрано: 2026-08-21"])
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


def test_build_second_barrier_catches_symlink_escaping_wiki_stati(tmp_path):
    """R2 ре-ревью: первая проверка (`_require_safe_path_component`) отбивает
    ВСЕ четыре других теста этого блока ещё до второго рубежа (`resolve()`
    внутри `wiki/Статьи`) — сам рубеж ни одним тестом не покрыт. `путь:
    Ссылка` не содержит ни одного разделителя, значит первая проверка его
    пропускает; если `Ссылка` — симлинк ВНУТРИ `wiki/Статьи`, ведущий наружу
    дерева, поймать обход обязан именно рубеж."""
    _write_inputs(tmp_path, "х", ["заголовок: Х", "путь: Ссылка", "собрано: 2026-08-21"])
    articles_dir = tmp_path / "wiki" / "Статьи"
    articles_dir.mkdir(parents=True)
    outside = tmp_path / "снаружи"
    outside.mkdir()
    (articles_dir / "Ссылка").symlink_to(outside, target_is_directory=True)
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


# --- коллизия заголовка статьи с именем/псевдонимом заметки зеркала --------
# (первый рубеж, ДО записи файла — не только последний, в `verify.py`, после
# того как статья уже полностью написана; задание тимлида после разбора
# «сколько таких коллизий будет на пилоте» — рутинный, не краевой случай).


def _write_mirror_note(tmp_path, key, aliases=()):
    """Минимальная заметка зеркала — `wiki/Источники/<key>.md`, только то,
    что нужно `check_mirror.build_notes_index`/`build_alias_index`: имя
    файла (сам `key`) и, если задан, `aliases` во frontmatter."""
    path = tmp_path / "wiki" / "Источники" / ("%s.md" % key)
    path.parent.mkdir(parents=True, exist_ok=True)
    front = "aliases: [%s]\n" % ", ".join('"%s"' % a for a in aliases) if aliases else ""
    path.write_text("---\n%s---\n\n# %s\n" % (front, key), encoding="utf-8")


def test_build_rejects_title_colliding_with_a_mirror_note_alias(tmp_path):
    """Живой случай пилота: тема форума «Тема 16109» названа человеком
    «Датчик детонации (ДД)» — Obsidian хранит в `aliases` уточнение в
    скобках отдельно не отсекая, но здесь достаточно точного совпадения
    заголовка статьи с ЦЕЛЫМ алиасом, чтобы показать механизм."""
    _write_mirror_note(tmp_path, "Тема 16109", aliases=["Датчик детонации"])
    _write_inputs(tmp_path, "х",
                  ["заголовок: Датчик детонации", "путь: Двигатель", "собрано: 2026-08-21"])
    with pytest.raises(articles.DraftError) as exc:
        articles.build("х", tmp_path)
    message = str(exc.value)
    assert "Датчик детонации" in message          # заголовок статьи назван
    assert "Тема 16109" in message                 # заметка-двойник названа
    assert "уточни заголовок" in message.lower()   # подсказан способ решения
    assert "subaru" not in message.lower()         # НЕ подсказан брендовый суффикс


def test_build_rejects_title_colliding_with_a_mirror_note_filename(tmp_path):
    """Коллизия по МАШИННОМУ имени заметки (не только по alias) — тот же
    рубеж, что различает `resolve_note`/`by_name`."""
    _write_mirror_note(tmp_path, "Расшифровка VIN")
    _write_inputs(tmp_path, "х",
                  ["заголовок: Расшифровка VIN", "путь: VIN", "собрано: 2026-08-21"])
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


def test_build_succeeds_with_a_unique_title_even_with_a_populated_mirror(tmp_path):
    """Обратная проверка: заметки зеркала есть, но заголовок статьи с ними
    не совпадает — сборка идёт как раньше, рубеж не даёт лишнего шума."""
    _write_mirror_note(tmp_path, "Тема 16109", aliases=["Датчик детонации"])
    _write_mirror_note(tmp_path, "Тема 14487", aliases=["Плохой запуск"])
    _write_inputs(tmp_path, "х",
                  ["заголовок: Диагностика датчика детонации", "путь: Двигатель",
                   "собрано: 2026-08-21"])
    out_path = articles.build("х", tmp_path)
    assert out_path == tmp_path / "wiki" / "Статьи" / "Двигатель" / "Диагностика датчика детонации.md"


def test_build_renaming_the_title_clears_the_collision(tmp_path):
    """Переименование заголовка в черновике снимает отказ — тот же вход
    (факты, тело), только другое имя."""
    _write_mirror_note(tmp_path, "Тема 16109", aliases=["Датчик детонации"])
    _write_inputs(tmp_path, "х",
                  ["заголовок: Датчик детонации", "путь: Двигатель", "собрано: 2026-08-21"])
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)

    _write_inputs(tmp_path, "х",
                  ["заголовок: Диагностика датчика детонации", "путь: Двигатель",
                   "собрано: 2026-08-21"])
    out_path = articles.build("х", tmp_path)
    assert out_path.exists()


def test_build_rebuilding_the_same_article_does_not_collide_with_itself(tmp_path):
    """Повторная сборка уже опубликованной статьи с тем же заголовком не
    должна считаться «коллизией» самой с собой — собственный, уже
    существующий на диске файл статьи исключается из совпадений тем же
    механизмом (`own_key`), что уже есть в `verify.py`."""
    _write_inputs(tmp_path, "х",
                  ["заголовок: Диагностика датчика детонации", "путь: Двигатель",
                   "собрано: 2026-08-21"])
    first = articles.build("х", tmp_path)
    assert first.exists()
    second = articles.build("х", tmp_path)  # пересборка того же черновика
    assert second == first


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


def test_marker_inside_obsidian_comment_is_not_used():
    """F3-бис ре-ревью: `%%…%%` — родной комментарий Obsidian, в режиме
    чтения невидим полностью (в отличие от HTML-комментария, который часть
    визоров всё же показывает) — самый актуальный способ спрятать маркер, и
    он не должен засчитываться как использование факта."""
    draft = "Утверждение без опоры в прозе.\n\n%% [^f1] %%\n"
    assert articles.used_ids(draft) == []
    out = articles.render(draft, [_fact("f1")], {"заголовок": "Х"})
    assert "неиспользованные_факты: [f1]" in out
    assert "## Сноски" not in out


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


# --- ревью задачи 5: R3 — фолбэк на mtime черновика убран целиком, `собрано`
# берётся только из явного поля frontmatter; уточнение бригадира ПОСЛЕ первой
# версии фикса — отсутствие поля ошибка (`DraftError`), а не молчаливый
# пропуск строки: та же схема, что у `путь`, и обязательная в том же смысле,
# не опциональная -----------------------------------------------------------
#
# Примечание об истории покрытия (R1 ре-ревью). До R3 `build` подставлял
# `собрано` из mtime черновика, если поле не было задано явно, и тест на это
# создавал черновик тут же в тесте — mtime файла совпадал с «сегодня», и
# мутация `date.fromtimestamp(mtime)` -> `date.today()` не валила НИ ОДНОГО
# теста (проверено руками, см. коммит на R1). R3 убирает саму ветку с mtime:
# у "источника даты" в `build` больше нет альтернативы явному полю — как и у
# `путь`, отсутствие поля обязано быть ошибкой, а не давать какой-либо иной
# результат.


def test_build_requires_explicit_собрано_field_even_with_a_usable_mtime(tmp_path):
    """Явное поле — единственный источник `собрано` в `build`, и его
    отсутствие — `DraftError`, а не молчаливый пропуск строки (уточнение
    бригадира: спека перечисляет `собрано` в составе полей статьи по
    контракту, а не как опцию). Заведомо старый, вполне пригодный на вид
    mtime черновика — стресс-тест на то, что build не соблазняется взять
    дату оттуда вместо явного поля."""
    _write_inputs(tmp_path, "х", ["заголовок: Х", "путь: Узел"])
    draft_path = tmp_path / "articles" / "черновики" / "х.md"
    os.utime(draft_path, (1_600_000_000, 1_600_000_000))  # 2020-09-13, заведомо не сегодня
    with pytest.raises(articles.DraftError):
        articles.build("х", tmp_path)


def test_build_uses_only_the_explicit_собрано_field_ignoring_mtime(tmp_path):
    """Явное `собрано:` во frontmatter черновика используется дословно, а
    заведомо другой mtime файла ничего не подмешивает и не переопределяет."""
    _write_inputs(tmp_path, "х", ["заголовок: Х", "путь: Узел", "собрано: 2020-09-13"])
    draft_path = tmp_path / "articles" / "черновики" / "х.md"
    os.utime(draft_path, (1_700_000_000, 1_700_000_000))  # 2023-11-14 — не совпадает с полем
    out_path = articles.build("х", tmp_path)
    text = out_path.read_text(encoding="utf-8")
    assert "собрано: 2020-09-13" in text
    assert "2023-11-14" not in text


# --- ревью задачи 5: F6 — «источников» считал факты, а не источники --------


def test_источников_counts_distinct_sources_not_facts():
    verified = [
        {"id": "f1", "источник": "Тема 1#Пост 1", "цитата": "а", "суть": "х"},
        {"id": "f2", "источник": "Тема 1#Пост 1", "цитата": "б", "суть": "х"},
        {"id": "f3", "источник": "Тема 1#Пост 2", "цитата": "в", "суть": "х"},
    ]
    out = articles.render("Т[^f1][^f2][^f3].", verified, {"заголовок": "Х"})
    assert "источников: 2" in out


def test_источников_counts_only_used_facts_not_all_verified():
    """R4 ре-ревью (F6-бис): факт, проверенный, но не упомянутый в прозе
    (`f3` ниже — он же в `неиспользованные_факты`), не должен увеличивать
    заявленный охват статьи — считать среди ИСПОЛЬЗОВАННЫХ фактов, а не всех
    проверенных."""
    verified = [
        {"id": "f1", "источник": "Тема 1#Пост 10", "цитата": "а", "суть": "х"},
        {"id": "f2", "источник": "Тема 1#Пост 10", "цитата": "б", "суть": "х"},
        {"id": "f3", "источник": "Тема 1#Пост 20", "цитата": "в", "суть": "х"},
    ]
    out = articles.render("Т[^f1].", verified, {"заголовок": "Х"})
    assert "источников: 1" in out
    assert "неиспользованные_факты: [f2, f3]" in out


# --- задача 5-бис: переименование заголовка оставляет сироту ---------------
#
# `check_mirror.check` (последний рубеж целостности) не видит осиротевший
# файл вовсе: ни битых ссылок, ни битых якорей — просто лишний файл, на
# который никто не ссылается. Чинится тем же приёмом, что и осиротевшие
# вложения (`mirror.prune_assets`), но по другому признаку: у вложений есть
# форма ИМЕНИ файла (`attachments.ASSET_NAME_RE`), у статьи заголовок и имя
# файла выбирает человек — то же самое, что делает автор личной заметки,
# положенной в тот же каталог руками. Признак поэтому не по имени, а по
# СОДЕРЖИМОМУ: `render()` безусловно пишет `type: статья` первой строкой
# frontmatter, и файл без этой строки не трогается никогда.


def test_build_renaming_the_title_removes_the_old_orphan_file(tmp_path):
    _write_inputs(tmp_path, "х", ["заголовок: Датчик детонации", "путь: Двигатель",
                                   "собрано: 2026-08-21"])
    old_path = articles.build("х", tmp_path)
    assert old_path.exists()

    _write_inputs(tmp_path, "х", ["заголовок: Датчик детонации Subaru", "путь: Двигатель",
                                   "собрано: 2026-08-21"])
    new_path = articles.build("х", tmp_path)

    assert new_path != old_path
    assert new_path.exists()
    assert not old_path.exists(), "переименование заголовка оставило старый файл-сироту"


def test_build_does_not_touch_a_foreign_file_placed_by_hand(tmp_path):
    """Личная заметка, положенная человеком в тот же каталог — без
    `type: статья` во frontmatter — не должна пострадать от уборки сирот,
    даже если она не соответствует ни одному черновику."""
    foreign = tmp_path / "wiki" / "Статьи" / "Двигатель" / "Личные заметки.md"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("---\ntype: заметка\n---\n\nМои личные мысли про двигатель.\n",
                        encoding="utf-8")

    _write_inputs(tmp_path, "х", ["заголовок: Датчик детонации", "путь: Двигатель",
                                   "собрано: 2026-08-21"])
    articles.build("х", tmp_path)

    assert foreign.exists(), "уборка сирот удалила чужой файл без нашего frontmatter-следа"
    assert "Мои личные мысли" in foreign.read_text(encoding="utf-8")


def test_build_rebuilding_the_same_draft_unchanged_deletes_nothing(tmp_path):
    _write_inputs(tmp_path, "х", ["заголовок: Датчик детонации", "путь: Двигатель",
                                   "собрано: 2026-08-21"])
    out_path = articles.build("х", tmp_path)
    before = sorted(p.relative_to(tmp_path) for p in (tmp_path / "wiki").rglob("*.md"))

    articles.build("х", tmp_path)
    after = sorted(p.relative_to(tmp_path) for p in (tmp_path / "wiki").rglob("*.md"))

    assert out_path.exists()
    assert before == after


def test_prune_orphans_does_nothing_when_drafts_directory_is_missing_or_empty(tmp_path):
    """Предохранитель, симметричный `prune_assets`: у вложений — «ни одной
    заметки не записано», у статей — «ни одного черновика не разобралось».
    Пустой/несуществующий каталог черновиков не должен читаться как «все
    статьи — сироты» и стирать существующее дерево из-за неверного `root`."""
    stray = tmp_path / "wiki" / "Статьи" / "Двигатель" / "Что-то.md"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("---\ntype: статья\n---\n\n# Что-то\n", encoding="utf-8")

    assert articles.prune_orphans(tmp_path) == 0
    assert stray.exists()


def test_frontmatter_model_as_single_string_is_not_split_into_letters():
    """Регрессия: `модель: xt-svx` строкой в черновике давала `[x, t, -, s, v, x]`."""
    out = articles.render("Текст[^f1].", [_fact("f1")],
                           {"заголовок": "Х", "узел": "эксплуатация", "модель": "xt-svx"})
    assert "модель: [xt-svx]" in out
