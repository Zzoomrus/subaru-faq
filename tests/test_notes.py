import ast
import re
from pathlib import Path

from pipeline import mirror, mirror_blog, mirror_faq, notes

NOTE = """---
tid: 42335
aliases: ["На Б10 ищу"]
---

# На Б10 ищу

##### Пост 391434

*Saka · 28.02.2015 18:35:30 · #1*

Ищу продольные рычаги (изображение не сохранилось: http://i.piccy.info/x.jpg)

##### Пост 391440

*Anri · 28.02.2015 21:10:32 · #2*

По 500р.
"""


def test_body_drops_frontmatter(tmp_path):
    p = tmp_path / "n.md"; p.write_text(NOTE, encoding="utf-8")
    assert "tid: 42335" not in notes.body(p)
    assert "# На Б10 ищу" in notes.body(p)


def test_section_ends_at_next_heading_of_any_level(tmp_path):
    p = tmp_path / "n.md"; p.write_text(NOTE, encoding="utf-8")
    s = notes.section(p, "Пост 391434")
    assert "Ищу продольные рычаги" in s
    assert "По 500р." not in s


def test_section_returns_none_for_missing_anchor(tmp_path):
    p = tmp_path / "n.md"; p.write_text(NOTE, encoding="utf-8")
    assert notes.section(p, "Пост 999999") is None


def test_citable_drops_generator_text(tmp_path):
    """Пометка об утрате — текст кода, а не автора.

    В зеркале таких 6341. Цитата, «подтверждённая» на этом тексте,
    подтверждает то, чего человек не писал, — и проверка при этом проходит.
    """
    p = tmp_path / "n.md"; p.write_text(NOTE, encoding="utf-8")
    s = notes.citable(notes.section(p, "Пост 391434"))
    assert "Ищу продольные рычаги" in s
    assert "изображение не сохранилось" not in s
    assert "28.02.2015" not in s          # строка «автор · дата» — тоже генератор


def test_citable_drops_empty_placeholders():
    assert "пустой комментарий" not in notes.citable("(пустой комментарий)\n\nреальный текст")
    assert "реальный текст" in notes.citable("(пустой комментарий)\n\nреальный текст")


# --- ревью задачи 3: находки 1-5, 184 нечищенных фрагмента на живом корпусе ---

NOTE_CENSORED_NICK = """---
tid: 24918
aliases: ["Тема с цензурой в нике"]
---

# Тема с цензурой в нике

##### Пост 204297

*Svetik**** Насонова · 10.01.2010 23:02:22 · #23*

ПРИВЕТИК я тоже катаюсь по Серпухову.

##### Пост 204298

*Anri · 11.01.2010 09:00:00 · #24*

Ответ.
"""


def test_citable_drops_post_header_with_asterisks_in_nickname(tmp_path):
    """Находка 1 ревью: форум цензурит часть ников звёздочками (6 живых
    постов темы 24918 в корпусе). Старый регэксп шапки `[^*\\n]+` запрещал
    `*` в куске «до даты» и не узнавал такую шапку вовсе — цитата
    «*Svetik**** Насонова · ... · #23*» проходила бы как слова автора.
    Шапку матчим структурой (курсив + дата), а не запретом звёздочки.
    """
    p = tmp_path / "n.md"
    p.write_text(NOTE_CENSORED_NICK, encoding="utf-8")
    s = notes.citable(notes.section(p, "Пост 204297"))
    assert "Svetik" not in s
    assert "10.01.2010" not in s
    assert "ПРИВЕТИК" in s


NOTE_BLOG_REPLY = """---
блог: "тест"
---

# Запись с ответом на комментарий

## Комментарии

##### Комментарий 10

*mangust · 25.11.2009 10:13:27*

Первый комментарий.

##### Комментарий 16

*Anri · 26.11.2009 08:00:00*

*(ответ на комментарий №10)*

Согласен с mangust.
"""


def test_citable_drops_reply_to_comment_marker(tmp_path):
    """Находка 2 ревью: `pipeline.mirror_blog.render_entry` вставляет
    `*(ответ на комментарий №N)*` под шапкой комментария-ответа — 178
    живых случаев в 60 файлах, паттерна под него не было вовсе.
    """
    p = tmp_path / "n.md"
    p.write_text(NOTE_BLOG_REPLY, encoding="utf-8")
    s = notes.citable(notes.section(p, "Комментарий 16"))
    assert "ответ на комментарий" not in s
    assert "Согласен с mangust" in s


def test_citable_drops_faq_question_and_answer_lost_placeholders():
    """Находка 3 (живая, 6 случаев) и латентная находка 4а (0 живых
    случаев сейчас, но код-путь реален): `pipeline.mirror_faq.render_entry`
    подставляет `(вопрос не сохранился)`/`(ответ не сохранился)`, когда
    поле пусто. Контракт зеркала прямо называет это текстом генератора.
    """
    assert notes.citable(mirror_faq.QUESTION_LOST).strip() == ""
    assert notes.citable(mirror_faq.ANSWER_LOST).strip() == ""


def test_citable_drops_blog_body_lost_placeholder():
    """Латентная находка 4б (0 живых случаев сейчас): `pipeline.
    mirror_blog.render_entry` подставляет `(текст не сохранился)`, когда
    `body_md` записи блога пуст."""
    assert notes.citable(mirror_blog.BODY_LOST).strip() == ""


def test_body_handles_degenerate_empty_frontmatter(tmp_path):
    """Находка 5 ревью: `text.find("\\n---\\n", 4)` не видел закрывающий
    разделитель вырожденного пустого frontmatter (`---\\n---\\n...`) —
    его ведущий `\\n` стоит на позиции 3, перед прежней стартовой позицией
    поиска. На живом корпусе не проявляется (все генераторы пишут хотя бы
    одно поле), но код-путь реален для будущего добора.
    """
    p = tmp_path / "n.md"
    p.write_text("---\n---\n\n# Title\nbody\n", encoding="utf-8")
    b = notes.body(p)
    assert not b.lstrip().startswith("---")
    assert "# Title" in b


# --- контрактный тест (по образцу test_anchor_contract.py) ---

#: Форма плейсхолдера-константы генератора: целиком в круглых скобках,
#: опционально в курсиве. AST-константы, а не regex по исходному тексту —
#: докстроки и комментарии не совпадают с этой формой ЦЕЛИКОМ, ложных
#: срабатываний на прозу не даёт (проверено: ровно 6 констант в трёх
#: генераторах на момент этой правки, все — известные плейсхолдеры).
_PLACEHOLDER_SHAPE = re.compile(r"^\(.*\)$|^\*\(.*\)\*$")


def _placeholder_literals(module) -> set[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _PLACEHOLDER_SHAPE.match(node.value.strip())
    }


def _fixed_parts(literal: str) -> list[str]:
    """Неизменные куски шаблона генератора вокруг `%s`/`%d` — то, что
    обязано пропасть из цитируемого текста независимо от подставленного
    значения."""
    return [part for part in re.split(r"%s|%d", literal) if part]


def test_every_generator_placeholder_literal_is_scrubbed_by_citable():
    """Контракт по образцу `tests/test_anchor_contract.py`: полнота
    `notes.GENERATOR_PATTERNS` проверяется механически по тому, что
    РЕАЛЬНО пишут генераторы, а не перечислением руками. Ревью задачи 3:
    список из четырёх видов в брифе уже отстал от генераторов на четыре
    плейсхолдера, и разошедшийся docstring («ни один плейсхолдер не
    процитируется») никто не проверял. Этот тест падает, если в
    `mirror`/`mirror_faq`/`mirror_blog` появится новая
    плейсхолдер-константа, не покрытая ни одним паттерном очистки.
    """
    literals = set()
    for module in (mirror, mirror_faq, mirror_blog):
        literals |= _placeholder_literals(module)
    assert literals, "эвристика _PLACEHOLDER_SHAPE ничего не нашла — проверь регэксп"
    for literal in literals:
        sample = literal.replace("%s", "http://example.org/x.jpg").replace("%d", "12345")
        scrubbed = notes.citable(sample)
        for fixed in _fixed_parts(literal):
            assert fixed not in scrubbed, "не вычищен фрагмент %r из плейсхолдера %r" % (fixed, literal)
