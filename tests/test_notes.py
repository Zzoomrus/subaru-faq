import ast
import importlib.util
import re
import types
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
    # `.strip() == ""` работало, пока замена шла на пробел; после фикса Н5
    # ревью задачи 4 (замена на несхлопываемый `notes._GAP`, не на пробел
    # — см. его докстринг) весь текст плейсхолдера схлопывается ровно в
    # один `_GAP`, а не в пустоту. Проверяем то же самое утверждение
    # («от плейсхолдера ничего, кроме разделителя, не осталось») новым
    # инвариантом.
    assert notes.citable(mirror_faq.QUESTION_LOST).strip() == notes._GAP
    assert notes.citable(mirror_faq.ANSWER_LOST).strip() == notes._GAP


def test_citable_drops_blog_body_lost_placeholder():
    """Латентная находка 4б (0 живых случаев сейчас): `pipeline.
    mirror_blog.render_entry` подставляет `(текст не сохранился)`, когда
    `body_md` записи блога пуст."""
    assert notes.citable(mirror_blog.BODY_LOST).strip() == notes._GAP


# --- ревью задачи 4 (Н1, Н5): цитирование чужих слов и сшивание фрагментов ---

NOTE_QUOTE_BLOCK = """---
tid: 10045
---

# Тема с цитированием

##### Пост 302230

*evil · 27.03.2012 15:00:00 · #1*

Передаточное отношение без разницы снимаш заднюю часть кпп и переставляеш в свою

##### Пост 302526

*KOLESO · 27.03.2012 16:00:00 · #2*

> evil пишет:
> Передаточное отношение без разницы снимаш заднюю часть кпп и переставляеш в свою

Согласен с evil, тоже так делал.
"""


def test_citable_drops_quote_block_content_and_its_header(tmp_path):
    """Н1 ревью задачи 4: `> <ник> пишет:` + `> …` — слова ДРУГОГО участника,
    перенесённые форумной цитатой в пост KOLESO. Без вычистки цитата из
    этого блока прошла бы гейт с подписью KOLESO, хотя слова написал evil
    (живой пример: тема 10045, пост 302526).
    """
    p = tmp_path / "n.md"
    p.write_text(NOTE_QUOTE_BLOCK, encoding="utf-8")
    s = notes.citable(notes.section(p, "Пост 302526"))
    assert "снимаш заднюю часть кпп" not in s   # тело чужой цитаты
    assert "evil пишет" not in s                # шапка цитаты — тоже не слова KOLESO
    assert "Согласен с evil" in s                # а вот это — собственные слова KOLESO


NOTE_OLD_ENGINE_QUOTE = """---
tid: 5555
---

# Тема со старым движком

##### Пост 900

*Иван · 15.03.2008 10:00:00 · #1*

Раньше меняли масло каждые 5 тысяч км.

##### Пост 901

*Пётр · 16.03.2008 11:00:00 · #2*

> Иван писал(а) 15.03.2008:
> Раньше меняли масло каждые 5 тысяч км.

А теперь достаточно 10 тысяч.
"""


def test_citable_drops_old_engine_quote_header_form(tmp_path):
    """Н1, доделка ре-ревью: старый движок форума писал шапку цитаты как
    `> <ник> писал(а) <дата>`, а не `пишет:` (863 таких прогона в живом
    корпусе). Детектор, ищущий буквально фразу «пишет:», эту форму бы
    пропустил и заново открыл дыру именно на старом движке — построчный
    `FOREIGN_QUOTE` (`^>.*$`) от формы шапки не зависит вовсе."""
    p = tmp_path / "n.md"
    p.write_text(NOTE_OLD_ENGINE_QUOTE, encoding="utf-8")
    s = notes.citable(notes.section(p, "Пост 901"))
    assert "Раньше меняли масло" not in s        # тело чужой цитаты (и её шапка)
    assert "А теперь достаточно 10 тысяч" in s   # собственные слова Петра


NOTE_HEADERLESS_QUOTE = """---
tid: 5556
---

# Тема без шапки цитаты

##### Пост 910

*Ольга · 01.04.2009 09:00:00 · #1*

> Тормозные колодки менять при остатке 2 мм.

Согласна, у меня так и было.
"""


def test_citable_drops_headerless_quote_block(tmp_path):
    """Н1, доделка ре-ревью: 784 прогона цитирования живого корпуса
    (143 273 знака) идут БЕЗ строки-шапки вовсе — просто `> …` сразу
    после шапки поста, ни «пишет:», ни «писал(а)» перед ними нет. Детектор
    по шапке-триггеру такую форму не увидел бы совсем — построчный
    `FOREIGN_QUOTE` видит её независимо от наличия фразы-триггера."""
    p = tmp_path / "n.md"
    p.write_text(NOTE_HEADERLESS_QUOTE, encoding="utf-8")
    s = notes.citable(notes.section(p, "Пост 910"))
    assert "Тормозные колодки менять при остатке" not in s
    assert "Согласна, у меня так и было" in s


def test_citable_gap_does_not_bridge_paragraphs_across_removed_placeholder(tmp_path):
    """Н5 ревью задачи 4: замена вычищенного текста на пробел (не на
    `notes._GAP`) превращала два абзаца, разделённых пометкой об утрате
    картинки, в СОСЕДНИЕ после схлопывания пробелов — цитата, идущая через
    эту границу в источнике, стала бы неотличима от честной непрерывной.
    """
    text = ("Первая часть предложения\n\n"
            "(изображение не сохранилось: http://i.piccy.info/x.jpg)\n\n"
            "вторая часть предложения")
    cleaned = notes.normalize_spaces(notes.citable(text))
    bridged = notes.normalize_spaces("Первая часть предложения вторая часть предложения")
    assert bridged not in cleaned
    # Обе половины по отдельности остаются дословно доступны — фикс не
    # портит обычную (не сшитую) цитату.
    assert notes.normalize_spaces("Первая часть предложения") in cleaned
    assert notes.normalize_spaces("вторая часть предложения") in cleaned


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

#: Комментарий-отвод для строк, которые ПОХОЖИ на плейсхолдер по форме, но
#: физически не попадают в тело заметки (отладочная печать и т.п.) — скан
#: смотрит только на форму строки, а не на то, куда она течёт, и не умеет
#: (и не должен уметь — разбор потока данных того не стоит) отличить одно
#: от другого сам. Действует ТОЛЬКО в третьем рубеже (`_line_has_skip_
#: marker`); рубежи 1 и 2 его не читают — см. docstring той функции.
_SKIP_COMMENT_MARKER = "notes: не текст заметки"


def _line_has_skip_marker(source_lines: list[str], lineno: int) -> bool:
    """Строка `lineno` (1-based) несёт комментарий-отвод
    `_SKIP_COMMENT_MARKER`. Отвод действует ТОЛЬКО в этом, третьем рубеже:
    рубежи 1 (`test_every_generator_placeholder_literal_is_scrubbed_by_
    citable`) и 2 (`test_every_generator_placeholder_constant_value_is_
    scrubbed_by_citable`) его не читают вовсе — значит промаркировать так
    настоящий плейсхолдер, поднятый в модульную константу, и спрятать его
    от очистки не получится: рубеж 2 проверяет ЗНАЧЕНИЕ константы
    независимо от того, что написано в комментарии на её строке."""
    if not (0 < lineno <= len(source_lines)):
        return False
    line = source_lines[lineno - 1]
    hash_pos = line.find("#")
    return hash_pos != -1 and _SKIP_COMMENT_MARKER in line[hash_pos:]


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


def _placeholder_violations_in_module(module) -> list[str]:
    """Ядро третьего рубежа для ОДНОГО модуля — читает только `module.
    __file__` как путь к исходнику, сам модуль импортировать не обязан.
    Общий код и для боевой проверки трёх генераторов, и для тестов на
    комментарий-отвод ниже (там модуль — синтетический временный файл)."""
    source = Path(module.__file__).read_text(encoding="utf-8")
    source_lines = source.splitlines()
    tree = ast.parse(source, filename=module.__file__)
    whitelisted = _module_level_constant_value_ids(tree)
    violations = []
    for node in ast.walk(tree):
        is_add = isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
        if not (isinstance(node, ast.JoinedStr) or is_add):
            continue
        if id(node) in whitelisted:
            continue
        if _line_has_skip_marker(source_lines, node.lineno):
            continue
        skeleton = _string_literal_skeleton(node)
        if skeleton is not None and _PLACEHOLDER_SKELETON_SHAPE.match(skeleton.strip()):
            violations.append("%s:%d — силуэт %r" % (module.__file__, node.lineno, skeleton))
    return violations


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

    ГРАНИЦА способа (доделка ревью №3): скан смотрит на ФОРМУ строки, а
    не на то, куда она реально течёт после сборки — он не разбирает поток
    данных (дороже пользы). Значит ложный отказ возможен: строка похожа
    на плейсхолдер по форме, но физически не попадает в тело заметки
    (пример ревьюера — отладочная печать `print(f"(пропущено: {tid})")`).
    Выход — комментарий-отвод `_SKIP_COMMENT_MARKER` на той же строке (см.
    `_line_has_skip_marker`); он назван прямо в тексте ошибки ниже, чтобы
    не лезть в исходник теста. Отвод НЕ открывает лазейку для настоящего
    плейсхолдера: он читается только здесь и не освобождает от рубежа 2,
    если строку всё-таки поднять в модульную константу (доказано тестом
    `test_line_marker_does_not_exempt_a_real_module_constant_placeholder`
    ниже).
    """
    violations = []
    for module in (mirror, mirror_faq, mirror_blog):
        violations.extend(_placeholder_violations_in_module(module))
    assert not violations, (
        "плейсхолдер записан динамической строкой прямо в месте использования, не "
        "поднят в модульную константу — очистка `pipeline.notes` его не увидит. Два "
        "выхода: (1) если строка ДОЛЖНА идти в текст заметки — поднять в модульную "
        "константу генератора (`IMAGE_LOST_TEMPLATE`-как); (2) если строка НЕ идёт в "
        "текст заметки (например, отладочная печать) — пометить её в конце строки "
        "комментарием `# %s` (скан его уважает). Нарушения: %s"
        % (_SKIP_COMMENT_MARKER, "; ".join(violations)))


def test_line_marker_opts_out_debug_prints_from_dynamic_placeholder_scan(tmp_path):
    """Боевой ложный отказ ревью (доделка №3): отладочная печать
    `print(f"(пропущено: {tid})")` похожа на плейсхолдер по форме, но в
    тело заметки не попадает вовсе — скан смотрит только на форму и не
    разбирает поток данных, значит без отвода это ложный отказ. Без
    пометки — тест обязан упасть (воспроизводит находку буквально); с
    пометкой `# notes: не текст заметки` — обязан пройти.
    """
    without_marker = 'def f(tid):\n    print(f"(пропущено: {tid})")\n'
    p1 = tmp_path / "fake_debug_print.py"
    p1.write_text(without_marker, encoding="utf-8")
    violations = _placeholder_violations_in_module(types.SimpleNamespace(__file__=str(p1)))
    assert violations, "отладочная печать без пометки обязана быть найдена — иначе ложный отказ не воспроизведён"

    with_marker = 'def f(tid):\n    print(f"(пропущено: {tid})")  # notes: не текст заметки\n'
    p2 = tmp_path / "fake_debug_print_marked.py"
    p2.write_text(with_marker, encoding="utf-8")
    violations2 = _placeholder_violations_in_module(types.SimpleNamespace(__file__=str(p2)))
    assert not violations2, "пометка обязана снимать ложный отказ, а не снимает: %r" % violations2


def test_line_marker_does_not_exempt_a_real_module_constant_placeholder(tmp_path):
    """Отвод не открывает лазейку. Комментарий-отвод читает только рубеж 3
    (AST исходника) — рубеж 2 (`test_every_generator_placeholder_constant_
    value_is_scrubbed_by_citable`) работает через `vars(module)` УЖЕ
    ИМПОРТИРОВАННОГО модуля, где комментариев не остаётся вовсе. Значит
    пометить пометкой РЕАЛЬНЫЙ плейсхолдер, поднятый в модульную
    константу, и спрятать его от очистки нельзя физически.

    Строим синтетический модуль с плейсхолдером-константой, помеченной
    той же пометкой, что использует предыдущий тест, — и показываем: (1)
    рубеж 3 её не флагует (правильно — она ПОДНЯТА в константу, это не
    обход, а ровно предписанный способ); (2) при этом константа
    прекрасно видна через `vars()` реально импортированного модуля и не
    вычищается `citable()` — то есть у настоящего генератора рубеж 2
    поймал бы её независимо от пометки в комментарии.
    """
    source = 'LEAK = "(вложение удалено модератором)"  # notes: не текст заметки\n'
    p = tmp_path / "fake_leak_module.py"
    p.write_text(source, encoding="utf-8")

    assert _placeholder_violations_in_module(types.SimpleNamespace(__file__=str(p))) == [], (
        "константу, поднятую по всем правилам, рубеж 3 не должен флагать — "
        "это не обход, а её и не должно тут ловить")

    spec = importlib.util.spec_from_file_location("fake_leak_module", p)
    real_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real_module)

    constants = _module_uppercase_string_constants(real_module)
    assert constants.get("LEAK") == "(вложение удалено модератором)", (
        "комментарий в исходнике не должен влиять на то, что видит `vars(module)` "
        "после импорта — а он не влияет, потому что комментарии не переживают импорт")
    assert "(вложение удалено модератором)" in notes.citable(constants["LEAK"]), (
        "рубеж 2 обязан был бы поймать эту константу как невычищенную независимо "
        "от пометки — у настоящего генератора без паттерна под неё это и произошло бы")


# --- числа с единицами измерения (задача 6 Ф3, `find_number_units`) --------
#
# Общая функция для `pipeline.facts` (потолок значений в цитате) и
# `pipeline.verify` (проверка 5) — перенесена сюда из `verify.py` ре-ревью
# задачи 6 (Н1/Н8/Н11): список ИСКЛЮЧЕНИЙ вместо списка разрешённого.


def test_find_number_units_treats_comma_and_dot_as_equal():
    assert notes.find_number_units("это 4,75 мм") == notes.find_number_units("это 4.75 мм")


def test_find_number_units_ignores_internal_spaces():
    assert notes.find_number_units("10 000 км") == {("10000", "km")}


def test_find_number_units_treats_attached_and_separated_units_as_equal():
    assert notes.find_number_units("11мм") == notes.find_number_units("11 мм")


def test_find_number_units_treats_latin_and_cyrillic_units_as_equal():
    assert notes.find_number_units("11 мм") == notes.find_number_units("11 mm")
    assert notes.find_number_units("5 кг") == notes.find_number_units("5 kg")


def test_find_number_units_splits_range_into_two_numbers():
    assert notes.find_number_units("10-12 мм") == {("10", "mm"), ("12", "mm")}


def test_find_number_units_compares_fraction_as_whole_string():
    """«Дюйма» сворачивается в ключ символа дюйма (`"`) таблицей синонимов
    (Н24 ре-ревью) — до нее это был отдельный ключ `dyuyma`, что не давало
    дробной форме источника (`3/16"`) подтвердить пересказ прозой словом
    (`3/16 дюйма`) и наоборот (см. Н24-тесты)."""
    assert notes.find_number_units("3/16 дюйма") == {("3/16", '"')}


def test_find_number_units_ignores_bare_numbers_without_unit():
    """Номер поста, год — без единицы измерения не проверяются."""
    assert notes.find_number_units("в 1992 году, пост #104015") == set()


def test_find_number_units_does_not_split_an_alphanumeric_identifier():
    """Н1-смежное: артикул/VIN — слитный идентификатор, а не «число с
    единицей». Без запрета на цифру сразу после единицы «22611» + «AD» из
    «22611AD982» читалось бы как число с единицей «AD»."""
    assert notes.find_number_units("артикул 22611AD982") == set()
    assert notes.find_number_units("VIN JF1GDDLF37G076103") == set()


def test_find_number_units_does_not_read_a_digit_run_embedded_in_an_identifier():
    """Живая находка (проверка на реальной статье «Расшифровка VIN Subaru»):
    у VIN `JF1GDDLF37G076103` цифровой хвост `076103` предшествован буквой
    («G076103»), и без запрета слева `076103` читался бы как САМОСТОЯТЕЛЬНОЕ
    число — а «076103 на форуме» (обычный предлог сразу после) давало бы
    ложную пару («76103», «на»), хотя «на» — предлог, а не единица."""
    assert notes.find_number_units("по VIN JF1GDDLF37G076103 на форуме расшифровали") == set()


# --- Н1 ре-ревью: список ИСКЛЮЧЕНИЙ вместо списка разрешённого --------------


def test_find_number_units_recognizes_mileage_in_thousands_of_km():
    """«тыс. км» — главная единица пробега домена, старый закрытый список
    (только «км») её не ловил вовсе (живая подделка ревью K3)."""
    assert notes.find_number_units("30-50 тыс. км") == {("30", "tyskm"), ("50", "tyskm")}
    # Три орфографических варианта одного и того же — один и тот же ключ.
    assert (notes.find_number_units("150 тыс. км") == notes.find_number_units("150 тыс.км")
            == notes.find_number_units("150 тыс км"))


def test_find_number_units_recognizes_units_outside_old_closed_list():
    """Живая подделка ревью A1 (расход топлива) стояла на «литра», которого
    не было в старом списке; % и л.с. — тоже реальные единицы домена.

    «Литра» сворачивается в ключ сокращения «л» таблицей синонимов (Н23
    ре-ревью) — до неё это был отдельный ключ `litra`, что и позволяло
    подделке, пересказывающей источник сокращением, уходить незамеченной
    (см. Н23-тесты ниже)."""
    assert notes.find_number_units("8,5 литра") == {("8.5", notes._canon_unit("л"))}
    assert notes.find_number_units("40%") == {("40", "%")}
    assert notes.find_number_units("100 л.с.") == {("100", notes._canon_unit("л.с."))}


def test_find_number_units_recognizes_inch_fraction_with_quote_mark():
    """Бриф: дробь `3/16` сравнивается как строка целиком — форма с
    дюймовой кавычкой (`3/16"`, 68 вхождений в живом корпусе) раньше не
    ловилась вовсе (единица не входила в закрытый список)."""
    assert notes.find_number_units('3/16"') == {("3/16", '"')}


def test_find_number_units_excludes_years_money_and_counts():
    """Год, деньги, штуки, разы — явные исключения (не единицы измерения),
    а НЕ молчаливый пропуск: список расширяется одной строкой, если найдётся
    ещё один частый нарушитель."""
    assert notes.find_number_units("в 1992 году") == set()
    assert notes.find_number_units("5000 руб.") == set()
    assert notes.find_number_units("5000 тыс.руб") == set()
    assert notes.find_number_units("3 шт.") == set()
    assert notes.find_number_units("10 раз") == set()


def test_find_number_units_excludes_english_ordinal_suffixes():
    """Живая находка (Тема 10045, таблица передаточных чисел КПП,
    скопированная из англоязычной спецификации): «Code 1st 2nd 3rd 4th 5th
    6th Rev.» без исключения читалось бы как шесть разных «чисел с
    единицей» («st», «nd», «rd», «th») — это порядковый суффикс
    числительного, а не единица измерения."""
    assert notes.find_number_units("Code 1st 2nd 3rd 4th 5th 6th Rev.") == set()


# --- Н15 ре-ревью: служебные слова — закрытый класс, не список -------------


def test_find_number_units_ignores_post_number_reference():
    """Бриф прямо требует НЕ проверять номер поста — живая находка: без
    запрета «в посте 104015 в теме» читалось как число «104015» с
    «единицей» «в» (предлог)."""
    assert notes.find_number_units("в посте 104015 в теме про VIN") == set()
    assert notes.find_number_units("обсуждали в #104015 в теме") == set()


def test_find_number_units_ignores_date_fragment():
    """Дата — служебный штамп времени, не факт домена; без масштабного
    запрета «13.02.2008» читалось как ДВА числа («13.02» затем «02.2008»),
    и следующее слово («выложил») — как единица."""
    assert notes.find_number_units("Таблицу 13.02.2008 выложил участник") == set()


def test_find_number_units_ignores_month_names():
    assert notes.find_number_units("Таблицу 13 февраля выложил") == set()
    assert notes.find_number_units("это было в марте прошлого года") == set()


def test_find_number_units_ignores_conjunctions_and_prepositions():
    assert notes.find_number_units("шли в 1992 и 1993 годах") == set()
    assert notes.find_number_units("выпускалась с 1998 по 2002 год") == set()


def test_find_number_units_ignores_known_non_unit_designations():
    """«4WD» — обозначение привода, не число с единицей «wd»."""
    assert notes.find_number_units("У этой версии 4WD и механика") == set()


# --- Н19 ре-ревью (регресс): регистр однобуквенного исключения решает ------


def test_find_number_units_recovers_uppercase_single_letter_units():
    """Регресс Н15: приведение регистра ДО проверки исключений сделало
    единицу «В» (вольт) неотличимой от предлога «в», «А» (ампер) — от
    союза «а». Живой масштаб — 162 и 113 вхождений на форуме; живая
    подделка — заниженный вдевятеро порог диагностики («< 0,1 В» источника
    против «< 0,9 В» статьи) проходила бы молча."""
    assert notes.find_number_units("напряжение 12 В") == {("12", "v")}
    assert notes.find_number_units("ток 5 А") == {("5", "a")}
    assert notes.find_number_units("порог 0,1 В") == {("0.1", "v")}


def test_find_number_units_still_excludes_lowercase_single_letter_function_words():
    """Регистр решает ТОЛЬКО для однобуквенных — строчная буква остаётся
    предлогом/союзом, как и было (Н15 не должна была перестать работать)."""
    assert notes.find_number_units("шли в 1992 и 1993 годах") == set()
    assert notes.find_number_units("это было с ним") == set()


# --- Н15-остаток: русские порядковые окончания и позиционные существительные


def test_find_number_units_ignores_ordinal_ending_attached_without_hyphen():
    """«2ой» без дефиса (дефис уже безопасен — «8-й» не приклеивается) —
    окончание порядкового прилагательного, закрытый класс русского языка."""
    assert notes.find_number_units("во 2ой цилиндр") == set()


def test_find_number_units_ignores_domain_position_nouns():
    """«3 передаче»/«4 цилиндре» — «в каком по счёту», не измерение;
    узкий, явно перечисленный список позиционных существительных домена
    (не путать со счётными — «6 витков» ниже остаётся легальным)."""
    assert notes.find_number_units("на 3 передаче") == set()
    assert notes.find_number_units("в 4 цилиндре") == set()


def test_find_number_units_does_not_touch_open_class_counting_nouns():
    """«виток» — счётное существительное, ОТКРЫТЫЙ класс (таких слов
    бесконечно много), трогать нельзя — это законный замер количества,
    не подделка, и он должен уйти в статистику пилота как есть."""
    assert notes.find_number_units("6 витков") == {("6", "vitkov")}


def test_find_number_units_ordinal_endings_do_not_break_ohm():
    """«Ом» (сопротивление) канонизируется в тот же ключ, что и падежное
    окончание «ом»/«ем» («в 3-ом») — эти два окончания сознательно НЕ
    попали в список именно поэтому (см. докстринг `_ORDINAL_ENDINGS`)."""
    assert notes.find_number_units("сопротивление 13 Ом") == {("13", "om")}


# --- Н19-продолжение: буква, начинающая новое предложение, — структура, ----
# а не список (тимлид отклонил сужение регистрового правила до «в»/«а»/«с»)


def test_find_number_units_does_not_bridge_a_paragraph_break():
    """Найденный механизм регресса: старый `_NUM` жадно проглатывал ЛЮБОЙ
    `\\s`, включая двойной перенос строки (границу абзаца), как «пробел
    внутри числа», и заглавная буква, начинающая СОВСЕМ ДРУГОЕ предложение
    после числа, читалась как «единица». Число внутри себя допускает
    только пробел-разделитель разрядов (обычный/неразрывный/узкий
    неразрывный), не перенос строки — граница абзаца/предложения после
    этого структурно недостижима для единицы, независимо от буквы."""
    assert notes.find_number_units(
        "координаты N55.43206 E38.23714\n\nИ так до упора") == set()
    assert notes.find_number_units(
        "Вопрос 3 и 4\n\nУ Чехословакии были свои проблемы") == set()
    assert notes.find_number_units(
        "О чём был вопрос номер 5\n\nО дальнейшем судить рано") == set()


def test_find_number_units_thousands_separator_still_works_after_the_fix():
    """Разрядный пробел («10 000») — законная часть числа, фикс не должен
    был его сломать (регресс, пойманный при первой попытке правки)."""
    assert notes.find_number_units("10 000 км") == {("10000", "km")}
    assert notes.find_number_units("это 4,75 мм") == {("4.75", "mm")}


def test_find_number_units_attached_suffix_after_number_is_a_known_residual():
    """Суффикс, ПРИКЛЕЕННЫЙ к числу без пробела (номер темы/детали вида
    «20120У») — тимлид явно разрешил не трогать: открытый класс, дело
    замеров пилота, а не подделка."""
    assert notes.find_number_units("TID=20120У") == {("20120", "u")}


# --- Н21 ре-ревью: ключ исключения — сырое слово, а не транслитерация ------


def test_find_number_units_extracts_liter_abbreviation():
    """До фикса «л» (литр) канонизировался транслитерацией в тот же ключ
    «l», что и частица «ль» (мягкий знак транслитерацией отбрасывался —
    `_CYR_TO_LAT["ь"] = ""`), и всегда классифицировался как служебное
    слово: литр в сокращении не извлекался НИКОГДА. Живая подделка —
    заниженный вдвое расход топлива («13,5 л»/«8,5 л» источника против
    «8,5 л»/«4,5 л» статьи) проходила бы молча, потому что гейт вообще не
    видел эту величину как число-с-единицей."""
    assert notes.find_number_units("расход 8,5 л по трассе") == {("8.5", "l")}


def test_find_number_units_still_excludes_the_particle_l():
    """«ль» по-прежнему служебное слово — фикс менял КЛЮЧ сравнения (сырое
    слово вместо транслитерации), а не убирал саму частицу из списка
    служебных слов. Оба токена («л» и «ль») строчные — регистровое правило
    Н19 тут ни при чём, различает их именно смена ключа."""
    assert notes._classify_unit("ль") == "strict"
    assert notes._classify_unit("л") is None


def test_find_number_units_canon_word_does_not_break_other_exclusions():
    """Смена ключа сравнения (`_canon_word` вместо `_canon_unit`) не должна
    задеть другие служебные слова/месяцы/окончания — они сравниваются без
    транслитерации, но остаются теми же словами."""
    assert notes.find_number_units("шли в 1992 и 1993 годах") == set()
    assert notes.find_number_units("Резьба под ключ 11 мм") == {("11", "mm")}
    assert notes.find_number_units("во 2ой цилиндр") == set()


# --- Н22 ре-ревью: канонизация числа снимает тот же набор пробелов, ---------
# что и разбор (неразрывный/узкий неразрывный), а не только ASCII-пробел.


def test_canon_number_strips_non_breaking_space_like_the_regular_space():
    assert notes._canon_number("130\xa0000") == "130000"
    assert notes._canon_number("130 000") == "130000"
    assert notes._canon_number("130 000") == "130000"


def test_find_number_units_treats_typographic_and_ascii_space_as_the_same_number():
    """Русская типографика набирает разрядный пробел НЕразрывным (чтобы
    число не разъезжалось по строкам при переносе) — то же число, набранное
    в статье и в цитате источника по-разному, обязано канонизироваться
    одинаково, иначе честное совпадение выглядело бы как расхождение."""
    assert notes.find_number_units("130\xa0000 км") == notes.find_number_units("130 000 км")
    assert notes.find_number_units("130\xa0000 км") == {("130000", "km")}


# --- Н23 ре-ревью: сокращение и слово целиком — одна единица ---------------
# ЕДИНСТВЕННЫЙ сознательно заведённый перечень в модуле (не класс/структура)
# — довод ревьюера принят: пропуск здесь даёт ГРОМКОЕ ложное отклонение
# честной статьи, а не молчаливую дыру для подделки (см. докстринг
# `notes._UNIT_SYNONYMS`), поэтому асимметрия с остальными находками фазы
# оправдана.


def test_find_number_units_unifies_abbreviation_and_full_word():
    """Проза статьи пишет сокращением, источник — словом целиком (или
    наоборот) — обязаны дать один и тот же ключ, иначе честная статья,
    пересказывающая цитату (обычное поведение ИИ-прозы), ложно отклоняется
    («число не встречается ни в одной сноске»)."""
    pairs = [
        ("13,5 л", "13,5 литра"),
        ("2 ч", "2 часа"),
        ("90%", "90 процентов"),
        ("100 км", "100 километров"),
        ("5 мм", "5 миллиметров"),
        ("80 кг", "80 килограммов"),
        ("12 В", "12 вольт"),
        ("5 А", "5 ампер"),
    ]
    for abbrev, word in pairs:
        assert notes.find_number_units(abbrev) == notes.find_number_units(word), (abbrev, word)
        assert notes.find_number_units(abbrev), abbrev  # обе стороны реально извлеклись, не совпали в set()


def test_find_number_units_synonyms_do_not_merge_different_units():
    """Обратная проверка, которую явно потребовал ре-ревью: таблица
    синонимов не должна склеить РАЗНЫЕ величины — «м»/«мм», «с»/«ч»,
    «кг»/«г» обязаны остаться разными ключами."""
    assert notes.find_number_units("5 м") != notes.find_number_units("5 мм")
    assert notes.find_number_units("5 ч") != notes.find_number_units("5 С")
    assert notes.find_number_units("5 кг") != notes.find_number_units("5 г")
    # и по значению, не только "не равно" — убедиться, что обе стороны вообще
    # извлекаются (иначе `set() != set()` было бы False, а не доказательством)
    assert notes.find_number_units("5 м") == {("5", "m")}
    assert notes.find_number_units("5 мм") == {("5", "mm")}
    assert notes.find_number_units("5 ч") == {("5", "ch")}
    assert notes.find_number_units("5 С") == {("5", "s")}
    assert notes.find_number_units("5 г") == {("5", "g")}
    assert notes.find_number_units("5 кг") == {("5", "kg")}


# --- Н24 ре-ревью: подбор групп синонимов «по интуиции» ненадёжен вообще —
# «минута»/«мин» пропущена не потому что редка, а потому что список брался
# «по памяти». Эта партия ГРУПП подобрана сканированием всего живого
# корпуса (см. `notes._UNIT_SYNONYMS`, комментарий над группами Н24):
# минута/мин, секунда/сек (добавлена сверх пяти названных ре-ревью — тот
# же класс, та же уверенность), градус/град, атмосфера+атмо/атм, бар
# (падежные формы), дюйм (падежные формы -> символ дюйма).


def test_find_number_units_unifies_abbreviation_and_full_word_н24():
    pairs = [
        ("5 мин", "5 минут"),
        ("30 сек", "30 секунд"),
        ("90 град", "90 градусов"),
        ("2 атм", "2 атмосферы"),
        ("2 атм", "2 атмо"),
        ("2 бар", "2 бара"),
        ('3/16"', "3/16 дюйма"),
    ]
    for abbrev, word in pairs:
        assert notes.find_number_units(abbrev) == notes.find_number_units(word), (abbrev, word)
        assert notes.find_number_units(abbrev), abbrev


def test_find_number_units_н24_synonyms_do_not_merge_different_units():
    """Та же обратная проверка для новой партии: «мин»/«м», «град»/«г»,
    «атм»/«а» (ампер) обязаны остаться разными ключами."""
    assert notes.find_number_units("5 мин") != notes.find_number_units("5 м")
    assert notes.find_number_units("5 град") != notes.find_number_units("5 г")
    assert notes.find_number_units("5 атм") != notes.find_number_units("5 А")
    assert notes.find_number_units("5 мин") == {("5", "min")}
    assert notes.find_number_units("5 м") == {("5", "m")}
    assert notes.find_number_units("5 град") == {("5", "grad")}
    assert notes.find_number_units("5 г") == {("5", "g")}
    assert notes.find_number_units("5 атм") == {("5", "atm")}
    assert notes.find_number_units("5 А") == {("5", "a")}


def test_find_number_units_atmosfernik_engine_type_is_not_folded_into_atm():
    """«Атмосферник» (двигатель без наддува) — прилагательное/существительное
    о ТИПЕ двигателя, не о давлении; сознательно НЕ включено в группу «атм»
    (живой пример: 8 вхождений на корпусе, но склейка дала бы ложное
    подтверждение величины давления через слово о типе мотора)."""
    assert notes.find_number_units("2.0 атмосферник") == {("2.0", "atmosfernik")}


def test_find_number_units_recognizes_kilo_ohm_written_with_internal_space():
    """Живая находка пилота статей (Тема 14487#Пост 87648): источник пишет
    «при 20 градусах он должен выдавать 3,0 К Ом» — с пробелом между «К» и
    «Ом», статья пересказывает то же значение слитно («3,0 кОм»). Значение
    одно, ключи без фикса разные (пробел рвёт единицу на «К» + отдельное
    слово прозы) — честная статья отклонялась.

    Пробел — орфографический шум того же типа, что точка в «тыс. км»
    (Н23/Н24), а не разделитель между единицей и следующим словом: снятие
    пробела НЕ должно склеивать число со случайным следующим словом прозы —
    «3,0 К отлично» остаётся тем, чем было (Н19: одиночная прописная «К» —
    сама по себе не исключение, читается как отдельная единица)."""
    ком = notes._canon_unit("кОм")
    assert notes.find_number_units("должен выдавать 3,0 К Ом, при 50") == {("3.0", ком)}
    assert notes.find_number_units("резистор на 3-4 к Ом") == {("3", ком), ("4", ком)}
    assert notes.find_number_units("должен выдавать 3,0 кОм") == {("3.0", ком)}
    # обратная проверка: «К» перед словом, не образующим «Ом», не склеивается
    assert notes.find_number_units("должен выдавать 3,0 К отлично") == {("3.0", "k")}


def test_find_number_units_recognizes_degree_symbol_as_synonym_of_gradus():
    """Живая находка пилота статей (Тема 14487#Пост 87648, статья «Плохой
    запуск двигателя»): источник пишет «при 20 градусах ... при 80
    градусах», статья пересказывает символом — «20°C», «80°C», «-20°C»,
    «0°C». «Градус» уже в таблице синонимов (группа «град»), но символ °
    (сам по себе или со следующей буквой шкалы, Latin `C` или кириллическое
    `С` — визуально неотличимы, а канонизация транслитерирует их в РАЗНЫЕ
    ключи, `c` и `s`) с этой группой не был связан вовсе.

    Формы подобраны СКАНИРОВАНИЕМ живого корпуса (48 689 постов), а не по
    памяти брифа: реальные написания — голый `°` (угол, 7 живых вхождений:
    угол опережения зажигания, продолжительность фаз, угол обзора — то же
    слово «градус», что и у температуры, ре-ревью Н24 уже свело угол и
    температуру в один ключ по лексическому признаку, не по физическому
    смыслу), `°C`/`°c` (10) и `°С`/`°с` (кириллица, 14 — визуально та же
    буква, но без свода канонизация транслитерирует её в другой ключ, `s`,
    не `c`).

    Обе гипотезы брифа сверх этого сканом НЕ подтвердились как безопасные:
    «0С» (ноль вместо знака градуса) — 0 живых вхождений вовсе (то, что
    похоже на этот паттерн при небрежном разборе, — хвост обычного числа,
    «-40С» целиком, а не «-4»+«0С»); «оС» (буква «о» вместо знака) — РЕАЛЬНА
    (1 живое вхождение, «до температуры 300 – 400оС»), но добавить её в
    синонимы нельзя: канонизация стирает мягкий знак и транслитерирует, и
    «оС» даёт ТОТ ЖЕ ключ («os»), что «ось»/«1ось» (счёт осей — реальное
    русское слово) и «OS» (код увеличенного размера в спецификациях деталей,
    «0.25 OS»). Синоним на уровне уже канонизированного ключа не может
    различить эти три источника — цена одного пропущенного живого вхождения
    меньше цены превратить счёт осей в ложную температуру, поэтому «оС»
    сознательно не тронута (см. обратную проверку ниже).

    Голая буква `C`/`c`/`С`/`с` БЕЗ знака градуса тоже сознательно НЕ
    включена: она уже занята частицей «с» (сотни живых «с»/«c» после
    числа — предлог «с»/«со», иногда набранный латиницей) и обозначением
    «с⁻¹» — скорость сдвига (живой пример «106 С-1», при слепом добавлении
    дало бы ложное «106 градусов»)."""
    assert notes.find_number_units("при 20 градусах") == notes.find_number_units("20°C")
    assert notes.find_number_units("при 80 градусах") == notes.find_number_units("80°C")
    assert notes.find_number_units("20°C") == {("20", notes._canon_unit("град"))}
    # кириллическая «С» визуально та же буква, канонизация другая без свода
    assert notes.find_number_units("20°С") == notes.find_number_units("20°C")
    assert notes.find_number_units("-20°C") == {("20", notes._canon_unit("град"))}
    assert notes.find_number_units("0°C") == {("0", notes._canon_unit("град"))}
    # угол (не температура) тем же словом «градус» — тот же ключ, уже так
    # было для слова целиком (Н24), символ обязан вести себя одинаково
    assert notes.find_number_units("на 5 – 15°") == {("5", notes._canon_unit("град")),
                                                       ("15", notes._canon_unit("град"))}
    # обратная проверка 1: голая «С»/«c» без знака градуса НЕ уходит в
    # «град» — частица «с» и «с⁻¹» (скорость сдвига) остаются собой
    assert notes.find_number_units("сдвига 106 С-1") == {("106", notes._canon_unit("С"))}
    assert notes.find_number_units("сдвига 106 С-1") != {("106", notes._canon_unit("град"))}
    # обратная проверка 2: «оС» (буква вместо знака градуса) сознательно НЕ
    # свёрнута с «град» — иначе счёт осей и код детали стали бы температурой
    assert notes._canon_unit("оС") == notes._canon_unit("ось") == notes._canon_unit("OS")
    assert notes.find_number_units("до температуры 400оС") != {("400", notes._canon_unit("град"))}
    assert notes.find_number_units("в подвешенном состоянии 1 ось") == {("1", notes._canon_unit("ось"))}
    assert notes.find_number_units("кольца 0.25 OS") == {("0.25", notes._canon_unit("OS"))}


# --- Н25 ре-ревью: множитель («тысяча»/«миллион»/«миллиард») теряет ---------
# единицу за собой не в двух названных формах, а во всём классе — прошедшая
# подделка (деньги источника подтверждают пробег статьи), худшая находка
# задачи: не отвергнутая честная статья, а пропущенная подмена.


def test_find_number_units_multiplier_captures_unit_in_every_spelling():
    """Диагноз: короткая ветка «тыс\\.?» стояла в альтернации ПЕРЕД длинной
    «тысяч[а-я]*» — Python берёт первую подошедшую, а не самую длинную, и на
    «тысяч» короткая ветка откусывала только «тыс», а «яч» доставалось
    следующему `_UNIT_WORD` как «единица» — настоящая единица дальше
    («км»/«рублей») терялась вовсе. Все написания множителя обязаны ловить
    единицу одинаково — «тыс.», «тыс», «тысяч», «тыщ» дают ОДИН ключ."""
    forms = ["тыс. км", "тыс км", "тысяч км", "тысячи км", "тыщ км", "тыщи км",
             "тысяч километров"]
    keys = {frozenset(notes.find_number_units("150 %s" % f)) for f in forms}
    assert keys == {frozenset({("150", "tyskm")})}, keys


def test_find_number_units_multiplier_distinguishes_money_from_mileage():
    """Живая подделка Н25: источник — «ради 3-5 тысяч рублей» (деньги),
    статья — «пробег... составлял 5 тысяч км» (пробег). Без фикса оба давали
    один и тот же вырожденный ключ «tysyach» (единица терялась вовсе), и
    цитата о деньгах молча подтверждала утверждение о пробеге."""
    money = notes.find_number_units("ради 3-5 тысяч рублей")
    mileage = notes.find_number_units("пробег этой машины составлял 5 тысяч км")
    assert money == {("3", "tysrubley"), ("5", "tysrubley")}
    assert mileage == {("5", "tyskm")}
    assert not (mileage <= money), "утверждение о пробеге не должно подтверждаться цитатой о деньгах"


def test_find_number_units_multiplier_alone_is_not_a_hard_unit():
    """«Продал за 150 тысяч» — множитель БЕЗ единицы за ним, число значимо
    само по себе (как цена/год), но НЕ единица измерения: обязано остаться
    отличимым от «150 тысяч км» и уйти в `find_quantity_claims`, а не
    молча потеряться и не стать вырожденной «единицей»."""
    assert notes.find_number_units("продал за 150 тысяч") == set()
    assert notes.find_number_units("отдам за 150 тыщ") == set()
    assert notes.find_number_units("продал за 150 тысяч") != notes.find_number_units("150 тысяч км")
    assert notes.find_quantity_claims("продал за 150 тысяч") == {"150"}
    assert notes.find_quantity_claims("отдам за 150 тыщ") == {"150"}


def test_find_number_units_multiplier_million_and_billion_forms():
    # «руб»/«р» (сокращение) — «мягкое» исключение денег само по себе
    # (`_QUANTITY_NOUNS`, Н16), поэтому «млн руб» уходит в quantity claims,
    # а не в hard unit — это ПРЕЖНЕЕ, не задетое Н25 поведение (то же для
    # «тыс. руб»). Полное слово «рублей»/«долларов» этим исключением не
    # накрыто и остаётся честной единицей — на нём и сравниваем написания.
    assert notes.find_number_units("2 млн рублей") == notes.find_number_units("2 миллиона рублей")
    assert notes.find_number_units("2 млрд долларов") == notes.find_number_units("2 миллиарда долларов")
    assert notes.find_number_units("2 млн долларов") != notes.find_number_units("2 млрд долларов")
    assert notes.find_number_units("2 млн рублей") == {("2", "mlnrubley")}
    assert notes.find_number_units("2 млрд долларов") == {("2", "mlrddollarov")}


def test_find_number_units_multiplier_does_not_glue_a_random_word():
    """«5 тысяч и 3 рубля» — «и» после множителя союз, не единица: не
    должен склеиться в бессмысленный составной ключ, множитель остаётся
    голым количеством (soft), а «3 рубля» — отдельная, честная единица."""
    assert notes.find_number_units("5 тысяч и 3 рубля") == {("3", "rublya")}
    assert notes.find_quantity_claims("5 тысяч и 3 рубля") == {"5"}


def test_attached_lowercase_k_means_thousand_and_is_a_soft_claim():
    """Н25: «"к" в значении тысячи, если встречается» — встречается (113
    чистых живых вхождений, всегда слитно и строчной буквой). Слитное
    написание — единственный надёжный сигнал, поэтому голая, отдельная
    проверка, а не ветка в общей цепочке `_classify_unit`."""
    assert notes.find_quantity_claims("пробег примерно 30к") == {"30"}
    assert notes.find_quantity_claims("установка обошлась 14к руб") == {"14"}
    assert notes.find_quantity_claims("на 5к-6к оборотах") == {"5", "6"}
    assert notes.find_number_units("пробег примерно 30к") == set()


def test_attached_lowercase_k_does_not_touch_kelvin_or_spaced_preposition():
    """Обратная проверка: заглавная «К» (Кельвин/кило-, слитно) и предлог
    «к» С ПРОБЕЛОМ («еду к 5 часам») остаются нетронутыми — разбор ведут
    ОДНОВРЕМЕННО регистр буквы И слитность написания, а не один признак.

    «3,0 К Ом» до фикса пилота статей (см.
    `test_find_number_units_recognizes_kilo_ohm_written_with_internal_space`)
    читалась как одиночная Кельвин/кило-«К» без «Ом» — этот пример убран
    отсюда, чтобы тест не фиксировал устаревшее (ложноотрицательное)
    поведение как контракт."""
    assert notes.find_number_units("биксенон 4300К") == {("4300", "k")}
    assert notes.find_number_units("приехал к 5 часам") == {("5", "ch")}
    assert notes.find_quantity_claims("приехал к 5 часам") == set()


# --- Н16 ре-ревью: голое число рядом с количественным существительным ------
# домена (год/лет/раз/шт/месяц/человек/деньги) — не единица, но САМО ЧИСЛО
# обязано проверяться, иначе исключение становится лазейкой для подмены.


def test_find_quantity_claims_extracts_year_beside_excluded_word():
    assert notes.find_quantity_claims("означает 1998 год") == {"1998"}


def test_find_quantity_claims_extracts_duration_and_count():
    assert notes.find_quantity_claims("Ресурс втулок 5 лет") == {"5"}
    assert notes.find_quantity_claims("зазор в 9 раза больше") == {"9"}


def test_find_quantity_claims_does_not_leak_into_find_number_units():
    """Число рядом с «мягким» исключением НЕ становится парой
    «число+единица» — `find_number_units` его не выдаёт вовсе, иначе
    считалось бы дважды двумя разными проверками."""
    assert notes.find_number_units("означает 1998 год") == set()


def test_find_bare_numbers_finds_year_without_a_neighbouring_word():
    """Сторона ИСТОЧНИКА: в цитате слова «год» рядом с числом может не
    быть вовсе — контракт зеркала §1, «8 - Год выпуска (С-1992)», год
    выпуска внутри скобок. `find_quantity_claims` тут ничего не найдёт
    (нет количественного существительного), нужен `find_bare_numbers`."""
    assert notes.find_quantity_claims("8 - Год выпуска (С-1992)") == set()
    assert notes.find_bare_numbers("8 - Год выпуска (С-1992)") == {"8", "1992"}


def test_find_bare_numbers_does_not_split_an_identifier():
    """Та же защита от VIN/артикула, что и у `find_number_units`."""
    assert notes.find_bare_numbers("артикул 22611AD982") == set()
    assert notes.find_bare_numbers("VIN JF1GDDLF37G076103") == set()


def test_find_bare_numbers_recognizes_money_suffix_glued_to_the_number():
    """Живая находка пилота статей (Тема 16109#Пост 306303): источник пишет
    ценник слитно — «подходит с новой волги и ценик 300р», статья
    пересказывает раздельно («около 300 руб.»). Деньги — не единица
    измерения (исключение, `_SOFT_QUANTITY_NOUNS`), поэтому число
    проверяется голым через `find_bare_numbers` на стороне цитаты — а он
    (в отличие от `find_quantity_claims`/`_extract_candidates`) требует,
    чтобы после числа не шла буква вовсе (защита от VIN/артикула), и «300р»
    слитно этой защитой ошибочно отбрасывался как хвост идентификатора.

    Денежный суффикс — ЗАКОНЧЕННЫЙ короткий список (те же сокращения, что
    уже в `_QUANTITY_NOUNS`: руб/р/тр), в отличие от единиц измерения,
    которых бесконечно много — поэтому это явное, узкое исключение из
    защиты, а не общее снятие запрета на букву после числа (VIN «22611AD982»
    остаётся отклонён)."""
    assert notes.find_bare_numbers("ценик 300р") == {"300"}
    assert notes.find_bare_numbers("ценик 300р.") == {"300"}
    assert notes.find_bare_numbers("ценик 300руб") == {"300"}
    assert notes.find_bare_numbers("ценик 300тр") == {"300"}
    # обратная проверка: VIN/артикул — не денежный суффикс, остаётся отклонён
    assert notes.find_bare_numbers("артикул 22611AD982") == set()
    assert notes.find_bare_numbers("300рублика") == set()  # не суффикс целиком, а начало другого слова


# --- Н17 ре-ревью: невидимые символы и разметка — по классу, не по перечню -


def test_find_number_units_strips_any_unicode_format_character():
    """Не три конкретных символа (Н8), а вся категория Unicode `Cf` —
    SOFT HYPHEN, ZERO WIDTH NON-JOINER/JOINER тоже категория `Cf` и не
    входили в старый перечень из трёх."""
    assert notes.find_number_units("9­мм") == {("9", "mm")}  # SOFT HYPHEN
    assert notes.find_number_units("9‌мм") == {("9", "mm")}  # ZWNJ
    assert notes.find_number_units("9‍мм") == {("9", "mm")}  # ZWJ


def test_find_number_units_strips_obsidian_highlight_and_strikethrough():
    assert notes.find_number_units("==9== мм") == {("9", "mm")}
    assert notes.find_number_units("~~9~~ мм") == {("9", "mm")}


def test_find_number_units_strips_html_tags_and_nbsp_entity():
    assert notes.find_number_units("<b>9</b> мм") == {("9", "mm")}
    assert notes.find_number_units("9&nbsp;мм") == {("9", "mm")}


def test_find_number_units_does_not_splice_sentence_after_abbreviation():
    """Общий паттерн «слово, точка, слово» откусил бы первое слово
    следующего предложения («руб. Итого» — не единица); составные формы
    перечислены явно и такого не делают."""
    assert notes.find_number_units("5000 руб. Итого потратил много") == set()


# --- Н8 ре-ревью: инлайн-разметка и невидимые символы не должны глушить проверку


def test_find_number_units_ignores_markdown_emphasis_around_number_or_unit():
    assert notes.find_number_units("**9** мм") == {("9", "mm")}
    assert notes.find_number_units("*9* мм") == {("9", "mm")}
    assert notes.find_number_units("9 *мм*") == {("9", "mm")}
    assert notes.find_number_units("**9 мм**") == {("9", "mm")}


def test_find_number_units_ignores_invisible_separators():
    assert notes.find_number_units("9​мм") == {("9", "mm")}  # zero width space
    assert notes.find_number_units("9⁠ мм") == {("9", "mm")}  # word joiner


def test_find_number_units_recognizes_typographic_dash_range():
    """Типографское тире в диапазоне (не ASCII-дефис) — раньше `_RANGE`
    требовал ровно `-` и обе стороны диапазона проходили не проверенными."""
    assert notes.find_number_units("7–4 мм") == {("7", "mm"), ("4", "mm")}
    assert notes.find_number_units("7—4 мм") == {("7", "mm"), ("4", "mm")}


def test_find_number_units_recognizes_two_dot_range_separator():
    """Живая находка пилота статей (Тема 16109#Пост 104598): источник пишет
    диапазон через ДВЕ точки — «обороты холостого хода 3300..3500 об/мин»,
    статья пересказывает тире («3300–3500 об/мин»). До фикса `_RANGE` ждал
    только дефис/тире, «3300..3500» не распознавалось диапазоном вовсе, и
    `_SINGLE` подхватывал только хвост («3500 об/мин»), а «3300» терялось
    без единицы — честная статья с тире не подтверждалась цитатой источника
    с двумя точками."""
    assert notes.find_number_units("обороты холостого хода 3300..3500 об/мин") == {
        ("3300", "ob/min"), ("3500", "ob/min")}
    assert (notes.find_number_units("обороты холостого хода 3300..3500 об/мин")
            == notes.find_number_units("обороты холостого хода 3300–3500 об/мин"))
    # другие живые формы того же разделителя на корпусе (давление, вольтаж)
    assert notes.find_number_units("0,1..0,5атм") == {("0.1", "atm"), ("0.5", "atm")}


def test_find_number_units_three_dot_ellipsis_is_not_a_range():
    """Обратная проверка: ТРИ точки — типографский эллипсис (живой пример
    корпуса: «0.7...1.0В»), а не разделитель диапазона; ровно ДВЕ точки —
    намеренная, узкая граница, не «две и более». На живом корпусе у трёх
    точек и больше 109 вхождений, почти все — усечение длинной
    ссылки/URL/координаты («55.76054...01929»), не диапазон значений: без
    границы первое число («0.7») в таких случаях осталось бы непроверяемым
    (как и раньше — фикс не расширяет разбор трёх точек, только двух)."""
    assert notes.find_number_units("0.7...1.0В") == {("1.0", notes._canon_unit("В"))}
    assert notes.find_number_units("55.76054...01929") == set()
    assert notes.find_number_units("t1151413...77 мм") == {("77", "mm")}


# --- границы абзаца (Н11 ре-ревью, второй раунд) — `quote_crosses_paragraph`


def test_quote_crosses_paragraph_is_false_when_quote_fits_in_one_paragraph():
    source = ("При 20 градусах сопротивление 3 Ом, при 50 градусах 5 Ом.\n\n"
              "Клиренс спереди у седана 266мм.")
    assert notes.quote_crosses_paragraph(
        "При 20 градусах сопротивление 3 Ом, при 50 градусах 5 Ом.", source) is False


def test_quote_crosses_paragraph_is_true_when_quote_spans_two_paragraphs():
    source = "Клиренс спереди у седана 266мм.\n\nКлиренс сзади у вагона 279мм."
    spliced = "Клиренс спереди у седана 266мм. Клиренс сзади у вагона 279мм."
    assert notes.quote_crosses_paragraph(spliced, source) is True


def test_quote_crosses_paragraph_ignores_whitespace_differences_within_a_paragraph():
    """Перенос строки ВНУТРИ одной мысли (мягкий перенос markdown) — не
    граница абзаца (Global Constraint фазы №1: перенос строки — не
    подделка); только ПУСТАЯ строка разделяет абзацы."""
    source = "Первая строка одной мысли,\nвторая строка той же мысли, 5 мм."
    quote = "Первая строка одной мысли, вторая строка той же мысли, 5 мм."
    assert notes.quote_crosses_paragraph(quote, source) is False


def test_quote_crosses_paragraph_table_rows_without_blank_lines_are_one_paragraph():
    """Живой случай (тема 10045, таблица передаточных чисел КПП): строки
    таблицы разделены ОДИНОЧНЫМ переносом, без пустой строки между ними —
    для этого правила это ОДИН абзац целиком, законный перечень."""
    source = "Строка 1: 3.454 2.062 1.448\nСтрока 2: 3.083 2.062 1.545\nСтрока 3: 3.166 1.882 1.296"
    assert notes.quote_crosses_paragraph(source, source) is False
