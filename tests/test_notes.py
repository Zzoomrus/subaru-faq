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
    """Контракт по образцу `tests/test_anchor_contract.py`, ВТОРОЙ рубеж
    (см. следующий тест для первого): AST-скан ловит константу, которую
    объявили, но забыли использовать где-либо в коде — сам факт, что в
    исходнике лежит строковый ЛИТЕРАЛ такой формы, уже требует очистки,
    независимо от того, дошёл ли он до вывода. Слепая зона этого способа —
    находка ревью (вторая доделка задачи 3): f-строка и конкатенация не
    являются одним `ast.Constant`, и такой плейсхолдер тест не найдёт —
    поэтому он не единственный рубеж, см. `test_every_generator_
    placeholder_constant_value_is_scrubbed_by_citable` ниже.
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


def _module_uppercase_string_constants(module) -> dict[str, str]:
    """Все заглавные строковые константы верхнего уровня модуля — как их
    видит Python ПОСЛЕ импорта, а не как они записаны в исходнике. Форма
    построения (литерал, f-строка, конкатенация, `%`-шаблон) для этого
    способа обнаружения не имеет значения: к моменту импорта модуля любая
    из них уже готовая строка ровно с тем именем, какое дал автор."""
    return {name: value for name, value in vars(module).items()
            if name.isupper() and isinstance(value, str)}


def test_every_generator_placeholder_constant_value_is_scrubbed_by_citable():
    """Контракт по РЕЗУЛЬТАТУ, а не по исходнику — первый и главный рубеж
    (вторая доделка ревью задачи 3). Прежний контракт сканировал AST на
    литеральный узел вида `(...)`/`*(...)*` — ревьюер впрыснул тот же по
    смыслу плейсхолдер f-строкой и конкатенацией, и AST-скан прошёл оба
    раза молча, хотя очистки под них не было: у f-строки литеральные куски
    лежат отдельными узлами `ast.Constant`, ни один не совпадает с формой
    ЦЕЛИКОМ; конкатенация — вообще не `ast.Constant`, а `ast.BinOp`.

    Раз весь смысл теста — поймать ЧУЖУЮ будущую правку, а не сегодняшний
    список из шести известных находок, форма записи в исходнике не должна
    иметь значения вовсе. Поэтому этот тест не читает исходный текст
    модулей: он берёт уже вычисленное ЗНАЧЕНИЕ каждой заглавной строковой
    константы (`vars(module)`, после импорта) и проверяет очистку по нему
    — литерал, f-строка, конкатенация после импорта неотличимы, все дают
    обычный `str`.
    """
    constants = []
    for module in (mirror, mirror_faq, mirror_blog):
        constants.extend((module, name, value)
                          for name, value in _module_uppercase_string_constants(module).items())
    assert constants, "не нашлось ни одной заглавной строковой константы — проверь модули"
    for module, name, literal in constants:
        sample = literal.replace("%s", "http://example.org/x.jpg").replace("%d", "12345")
        scrubbed = notes.citable(sample)
        for fixed in _fixed_parts(literal):
            assert fixed not in scrubbed, (
                "%s.%s не вычищена целиком (форма записи в исходнике не важна — "
                "значение всё равно %r)" % (module.__name__, name, literal))


# --- третий рубеж: динамическая строка-плейсхолдер БЕЗ подъёма в константу ---

#: Форма плейсхолдера — как в `_PLACEHOLDER_SHAPE`, но `re.S`: место
#: интерполяции f-строки в силуэте помечено `\0`, а `.` по умолчанию не
#: матчит перевод строки — здесь это неважно (плейсхолдеры однострочные),
#: но `\0` не должен зависеть от этой тонкости.
_PLACEHOLDER_SKELETON_SHAPE = re.compile(r"^\(.*\)$|^\*\(.*\)\*$", re.S)


def _string_literal_skeleton(node) -> str | None:
    """Силуэт строкового ВЫРАЖЕНИЯ — если оно целиком составлено из
    литералов/f-строк/конкатенации: место интерполяции f-строки — `\0`
    (форма скобок вокруг него не меняется, а точное подставленное значение
    для решения «похоже на плейсхолдер» не нужно). Если где-то в дереве
    встретился вызов функции, имя переменной и т.п. — результат неизвестен
    статически, возвращает `None`: такое выражение не флагуется вовсе (тот
    же принцип, что у `_templated` в `notes.py` — не гадать, а не
    подставлять безопасное предположение), это и держит тест без ложных
    срабатываний на честный код (форма 5 ревью — `"\\n".join(out) + "\\n"`
    и подобные: `Call`/`Name` внутри конкатенации возвращают `None`).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.FormattedValue):
                parts.append("\0")
            elif isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _string_literal_skeleton(node.left)
        right = _string_literal_skeleton(node.right)
        return None if left is None or right is None else left + right
    return None


def _module_level_constant_value_ids(tree: ast.Module) -> set[int]:
    """`id()` выражений, стоящих правой частью присваивания ЗАГЛАВНОМУ
    имени верхнего уровня модуля — их значение уже проверяется по
    результату (`test_every_generator_placeholder_constant_value_is_
    scrubbed_by_citable`), здесь флагать их вторично незачем."""
    ids = set()
    for stmt in tree.body:
        if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id.isupper()):
            ids.add(id(stmt.value))
        elif (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
                and stmt.target.id.isupper() and stmt.value is not None):
            ids.add(id(stmt.value))
    return ids


def test_dynamic_placeholder_shaped_strings_must_be_module_constants():
    """Третий рубеж (доделка ревью №2 — четвёртая проверенная форма):
    плейсхолдер, собранный f-строкой или конкатенацией ПРЯМО в месте
    использования, без подъёма в модульную константу, не виден НИ ОДНОМУ
    из двух прежних рубежей — по разным причинам. Новый (`test_every_
    generator_placeholder_constant_value_is_scrubbed_by_citable`) смотрит
    только `vars(module)` после импорта: локальное выражение внутри тела
    функции никогда не становится атрибутом модуля, эта проверка его
    физически не увидит. Старый (AST по литералу) видит только цельный
    `ast.Constant` — f-строка и конкатенация вообще не такой узел, эта
    слепая зона была явной причиной первой доделки. Ревьюер поймал ровно
    инлайновую f-строку в генераторе блогов, минуя оба рубежа молча.

    Способ — не «найти и вычистить» (для инлайнового выражения чистить
    и незачем, оно нигде не становится доступной константой), а «запретить
    писать так»: конвенция этой задачи — «плейсхолдер обязан быть модульной
    константой» — становится проверяемой, а не пожеланием. AST-обход
    находит f-строки/конкатенации ГДЕ УГОДНО в модуле; если их силуэт
    (`_string_literal_skeleton`) выглядит как плейсхолдер и выражение НЕ
    является прямой правой частью присваивания заглавному имени верхнего
    уровня — тест падает с указанием поднять его в константу.

    Ложных срабатываний на честный код не даёт по двум причинам: (1)
    выражения, из которых силуэт не восстановить целиком статически
    (вызов функции, переменная — например `"\\n".join(out) + "\\n"`, оба
    таких `BinOp` в `mirror.py`/`mirror_blog.py` на момент этой правки),
    не флагуются вовсе; (2) обычная f-строка/конкатенация, силуэт которой
    не имеет формы `(...)`/`*(...)*`, не совпадает с `_PLACEHOLDER_
    SKELETON_SHAPE` и проходит — проверено инъекцией такой строки в
    ревью (форма 5: `f"Комментарий {comment_id}"`).
    """
    violations = []
    for module in (mirror, mirror_faq, mirror_blog):
        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=module.__file__)
        whitelisted = _module_level_constant_value_ids(tree)
        for node in ast.walk(tree):
            is_add = isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
            if not (isinstance(node, ast.JoinedStr) or is_add):
                continue
            if id(node) in whitelisted:
                continue
            skeleton = _string_literal_skeleton(node)
            if skeleton is not None and _PLACEHOLDER_SKELETON_SHAPE.match(skeleton.strip()):
                violations.append("%s:%d — силуэт %r" % (module.__file__, node.lineno, skeleton))
    assert not violations, (
        "плейсхолдер записан динамической строкой прямо в месте использования, "
        "не поднят в модульную константу — очистка `pipeline.notes` его не увидит: "
        + "; ".join(violations))
