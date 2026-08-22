"""Проверяльщик готовой статьи (задача 6 Ф3) — главный тест проекта (спека
§8): проверяльщику, который не ловит подделку, верить нельзя, поэтому его
самого проверяют враньём.

`tests/подделки/*.md` — по файлу на каждый вид подделки, каждый ОБЯЗАН
упасть (`test_every_fake_article_is_caught`). Контрольный тест
(`test_honest_article_passes`) собирает ЧЕСТНУЮ статью через настоящий
конвейер (`facts.check_all` -> `articles.render`) и проверяет, что она
проходит — без него проверяльщик, отвергающий всё подряд, тоже был бы
«зелёным».

Мир подделок (`mirror`/`conn` ниже) устроен так, чтобы каждая подделка
падала РОВНО на одной проверке — см. таблицу «проверка -> подделка» в
`task-6-report.md`.
"""
import sqlite3
from pathlib import Path

import pytest

from pipeline import articles, db, facts, verify

FAKES = Path(__file__).parent / "подделки"

# --- Тема 1: живой пост с числами (дробь, десятичная запятая, диапазон) ----
THEME_1 = """---
tid: 1
---

# Тормоза

##### Пост 100

*Razum · 11.10.2014 12:00:00 · #1*

Трубки нужны 3/16 дюйма, это   4,75 мм. Резьба под ключ 11. Зазор в клапанах должен быть 10-12 мм.

##### Пост 101

*Anri · 11.10.2014 13:00:00 · #2*

(изображение не сохранилось: http://i.piccy.info/x.jpg)
"""

# --- Тема 2: пост с реальным переносом абзаца внутри цитируемого текста ----
# (живой случай ре-ревью задачи 5: `12 - Коробка передач` и `В: механическая
# 5-ти ступенчатая» стоят в источнике отдельными абзацами).
THEME_2_MULTILINE = """---
tid: 2
---

# VIN

##### Пост 200

*Antoha_samara · 13.02.2008 12:00:00 · #1*

12 - Коробка передач

В: механическая 5-ти ступенчатая
"""

# --- Тема 4: цитирование чужих слов внутри поста (для подделки Н9) --------
THEME_4_QUOTED = """---
tid: 4
---

# Обсуждение КПП

##### Пост 400

*evil · 27.03.2012 15:00:00 · #1*

Передаточное отношение без разницы снимаш заднюю часть кпп и переставляеш в свою

##### Пост 401

*KOLESO · 27.03.2012 16:00:00 · #2*

> evil пишет:
> Передаточное отношение без разницы снимаш заднюю часть кпп и переставляеш в свою

Согласен с evil, тоже так делал.
"""

# --- Тема 5: два абзаца, в каждом своё значение (Н11, второй раунд) --------
# Для «обратной подделки» — склейки двух абзацев с ровно двумя значениями
# суммарно (по требованию тимлида после замера живого корпуса).
THEME_5_TWO_PARAGRAPHS = """---
tid: 5
---

# Клиренс

##### Пост 500

*allrad · 20.02.2009 12:00:00 · #1*

Клиренс спереди у седана 266мм.

Клиренс сзади у вагона 279мм.
"""

# --- Тема 3: пустая тема форума — ни одного поста ---------------------------
THEME_3_EMPTY = """---
tid: 3
---

# Пустая тема

> [!missing] содержимое не сохранилось
"""

FAQ_100 = """# Интервал замены масла

##### Вопрос

Как часто менять масло?

##### Ответ

Рекомендуемый интервал замены масла 5000 км пробега.
"""

# Дубль FAQ 100 старым движком — текст тот же, но запись помечена дублем в
# базе (см. фикстуру `conn`).
FAQ_OLD_9 = """# Интервал замены масла (старая страница)

##### Вопрос

Как часто менять масло?

##### Ответ

Рекомендуемый интервал замены масла 5000 км пробега.
"""

# Выдержка блога — текст настоящий (восстановлен из ленты), но is_excerpt=1
# в базе (см. `conn`) запрещает цитировать её как дословный источник.
BLOG_77_EXCERPT = """# Блог: ремонт

##### Запись

Тормозные диски изнашиваются быстрее в городе.
"""


@pytest.fixture
def mirror(tmp_path):
    root = tmp_path / "Источники"
    root.mkdir()
    (root / "Тема 1.md").write_text(THEME_1, encoding="utf-8")
    (root / "Тема 2.md").write_text(THEME_2_MULTILINE, encoding="utf-8")
    (root / "Тема 3.md").write_text(THEME_3_EMPTY, encoding="utf-8")
    (root / "Тема 4.md").write_text(THEME_4_QUOTED, encoding="utf-8")
    (root / "Тема 5.md").write_text(THEME_5_TWO_PARAGRAPHS, encoding="utf-8")
    (root / "FAQ 100.md").write_text(FAQ_100, encoding="utf-8")
    (root / "FAQ старый 9.md").write_text(FAQ_OLD_9, encoding="utf-8")
    (root / "Блог remont 77.md").write_text(BLOG_77_EXCERPT, encoding="utf-8")
    return root


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    db.init_schema(c)
    c.execute("INSERT INTO posts(mid, tid, author, posted_at, text, markdown) "
              "VALUES (100, 1, 'Razum', '2014-10-11 12:00:00', '', '')")
    c.execute("INSERT INTO posts(mid, tid, author, posted_at, text, markdown) "
              "VALUES (101, 1, 'Anri', '2014-10-11 13:00:00', '', '')")
    c.execute("INSERT INTO posts(mid, tid, author, posted_at, text, markdown) "
              "VALUES (200, 2, 'Antoha_samara', '2008-02-13 12:00:00', '', '')")
    c.execute("INSERT INTO posts(mid, tid, author, posted_at, text, markdown) "
              "VALUES (400, 4, 'evil', '2012-03-27 15:00:00', '', '')")
    c.execute("INSERT INTO posts(mid, tid, author, posted_at, text, markdown) "
              "VALUES (401, 4, 'KOLESO', '2012-03-27 16:00:00', '', '')")
    c.execute("INSERT INTO posts(mid, tid, author, posted_at, text, markdown) "
              "VALUES (500, 5, 'allrad', '2009-02-20 12:00:00', '', '')")
    c.execute("INSERT INTO faq(engine, nr, question, answer_md, answer_text) "
              "VALUES ('bitrix', 100, 'Как часто менять масло?', "
              "'Рекомендуемый интервал замены масла 5000 км пробега.', "
              "'Рекомендуемый интервал замены масла 5000 км пробега.')")
    c.execute("INSERT INTO faq(engine, nr, question, answer_md, answer_text, "
              "duplicate_of_engine, duplicate_of_nr) "
              "VALUES ('old', 9, 'Как часто менять масло?', "
              "'Рекомендуемый интервал замены масла 5000 км пробега.', "
              "'Рекомендуемый интервал замены масла 5000 км пробега.', 'bitrix', 100)")
    c.execute("INSERT INTO blog_posts(blog, post_id, author, posted_at, body_md, is_excerpt) "
              "VALUES ('remont', 77, 'ИгорьБлог', '01.01.2015 10:00:00', '', 1)")
    c.commit()
    return c


# --- главный тест проекта: каждая подделка обязана упасть -------------------


@pytest.mark.parametrize("подделка", sorted(p.name for p in FAKES.iterdir()))
def test_every_fake_article_is_caught(подделка, mirror, conn):
    result = verify.check(FAKES / подделка, mirror, mirror, conn)
    assert not result["ок"], "подделка %s прошла проверку — проверяльщику нельзя верить" % подделка
    assert result["проблемы"], "ок=False обязан сопровождаться хотя бы одной причиной (%s)" % подделка


def test_article_name_colliding_with_source_note_is_rejected(mirror, conn):
    """Замечание тимлида (ре-ревью соседа): `check_mirror.check` эту дыру не
    увидит НИКОГДА — он объединяет вики-дерево `Источники/` + `Статьи/` и
    для одноимённых заметок в разных папках сверяет якорь по ОБЪЕДИНЕНИЮ, а
    не отказывает. Если статья называется так же, как реальный источник
    («Тема 1.md» — файл `tests/подделки/Тема 1.md`, специально совпадающий
    с «Тема 1» из фикстуры `mirror`), сноска на этот источник после сборки
    в общее дерево может молча резолвиться в саму статью."""
    result = verify.check(FAKES / "Тема 1.md", mirror, mirror, conn)
    assert not result["ок"]
    assert any("совпадает с именем/алиасом заметки" in p for p in result["проблемы"])


def test_name_collision_check_is_case_insensitive(mirror, conn, tmp_path):
    """Н12 ре-ревью: Obsidian резолвит вики-ссылки БЕЗ учёта регистра —
    «тема 1» и «Тема 1» для него одно и то же имя, значит и проверка
    коллизии обязана сравнивать без учёта регистра, а не точной строкой."""
    p = tmp_path / "тема 1.md"
    p.write_text("---\ntype: статья\nисточников: 0\nсобрано: 2026-08-22\n---\n\n# тема 1\n\nтекст.\n",
                 encoding="utf-8")
    result = verify.check(p, mirror, mirror, conn)
    assert not result["ок"]
    assert any("совпадает с именем/алиасом заметки" in x for x in result["проблемы"])


def test_name_collision_check_sees_alias_space_not_only_filenames(mirror, conn, tmp_path):
    """Н12/Н14 ре-ревью: у заметок зеркала машинное имя файла (`Тема N`), но
    человек называет статью, скорее всего, так же, как названа тема форума
    (`aliases`) — коллизия возможна там, а не в пространстве машинных имён."""
    (mirror / "Тема 1.md").write_text(
        THEME_1.replace("---\ntid: 1\n---", '---\ntid: 1\naliases: ["Провалы в работе ДВС"]\n---'),
        encoding="utf-8")
    p = tmp_path / "Провалы в работе ДВС.md"
    p.write_text(
        "---\ntype: статья\nисточников: 0\nсобрано: 2026-08-22\n---\n\n# Провалы в работе ДВС\n\nтекст.\n",
        encoding="utf-8")
    result = verify.check(p, mirror, mirror, conn)
    assert not result["ок"]
    assert any("совпадает с именем/алиасом заметки" in x for x in result["проблемы"])


def test_alias_link_in_prose_resolves(mirror, conn, tmp_path):
    """Н14 ре-ревью: ссылка «смотри также» по человеческому названию темы
    (alias), а не по машинному имени `Тема N` — Obsidian такую ссылку
    резолвит, `resolve_note` (только по имени файла) — нет."""
    (mirror / "Тема 1.md").write_text(
        THEME_1.replace("---\ntid: 1\n---", '---\ntid: 1\naliases: ["Провалы в работе ДВС"]\n---'),
        encoding="utf-8")
    article = ("---\ntype: статья\nисточников: 0\nсобрано: 2026-08-22\n---\n\n"
               "# Другая статья\n\nПодробнее — [[Провалы в работе ДВС]].\n")
    p = tmp_path / "Другая статья.md"
    p.write_text(article, encoding="utf-8")
    result = verify.check(p, mirror, mirror, conn)
    assert not any("не резолвится" in x for x in result["проблемы"]), result["проблемы"]


def test_cross_article_see_also_link_is_not_a_false_positive(mirror, conn, tmp_path):
    """Н5 ре-ревью: ссылка «смотри также» на ДРУГУЮ статью — не подделка;
    раньше индекс строился только по `Источники/`, и такая ссылка считалась
    выдуманной. `wiki_root` теперь охватывает и `Статьи/`."""
    wiki_root = mirror.parent
    other = wiki_root / "Статьи" / "Прочее" / "Другая статья.md"
    other.parent.mkdir(parents=True)
    other.write_text("---\ntype: статья\n---\n\n# Другая статья\n\nтекст.\n", encoding="utf-8")

    p = tmp_path / "статья.md"
    p.write_text(
        "---\ntype: статья\nисточников: 0\nсобрано: 2026-08-22\n---\n\n"
        "# Своя статья\n\nСм. также [[Другая статья]].\n",
        encoding="utf-8")
    result = verify.check(p, wiki_root, mirror, conn)
    assert not any("не резолвится" in x for x in result["проблемы"]), result["проблемы"]


def test_two_articles_sharing_a_title_collide_with_each_other(mirror, conn):
    """Н13 ре-ревью: коллизия имени возможна и между ДВУМЯ СТАТЬЯМИ, не
    только между статьёй и источником — прежняя проверка смотрела только в
    `Источники/` и такую пару не видела вовсе."""
    wiki_root = mirror.parent
    a = wiki_root / "Статьи" / "Двигатель" / "Зазоры клапанов.md"
    b = wiki_root / "Статьи" / "Ходовая" / "Зазоры клапанов.md"
    for p in (a, b):
        p.parent.mkdir(parents=True)
        p.write_text("---\ntype: статья\n---\n\n# Зазоры клапанов\n\nтекст.\n", encoding="utf-8")

    for p in (a, b):
        result = verify.check(p, wiki_root, mirror, conn)
        assert not result["ок"], p
        assert any("совпадает с именем/алиасом заметки" in x for x in result["проблемы"])


# --- контрольный случай: честная статья обязана пройти ----------------------


def test_honest_article_passes(mirror, conn, tmp_path):
    """Без этого теста проверяльщик, отвергающий всё подряд, тоже был бы
    «зелёным» на тесте подделок (спека §8, бриф задачи 6, шаг 2). Статья
    собрана НАСТОЯЩИМ конвейером — `facts.check_all` -> `articles.render`,
    не переписана вручную — иначе тест проверял бы согласие verify.py со
    своими собственными ожиданиями, а не с продукцией предыдущих задач фазы.
    """
    raw = [
        {"источник": "Тема 1#Пост 100",
         "цитата": "Трубки нужны 3/16 дюйма, это   4,75 мм", "суть": "диаметр трубок"},
        {"источник": "Тема 1#Пост 100",
         "цитата": "Зазор в клапанах должен быть 10-12 мм", "суть": "зазор клапанов"},
        {"источник": "FAQ 100#Ответ",
         "цитата": "Рекомендуемый интервал замены масла 5000 км пробега", "суть": "интервал масла"},
    ]
    result = facts.check_all(raw, mirror, conn)
    assert result["статистика"]["отброшено"] == 0, result["отброшено"]

    draft = ("Тормозные трубки — 3/16 дюйма, это 4,75 мм[^f1]. "
             "Зазор в клапанах должен быть 10-12 мм[^f2]. "
             "Масло меняется каждые 5000 км[^f3].\n")
    meta = {"заголовок": "Контрольная статья", "узел": "тест", "собрано": "2026-08-22"}
    text = articles.render(draft, result["проверено"], meta)
    out_path = tmp_path / "статья.md"
    out_path.write_text(text, encoding="utf-8")

    v = verify.check(out_path, mirror, mirror, conn)
    assert v["ок"], v["проблемы"]
    assert v["источники_без_цитаты"] == []

    # Н6 ре-ревью: с `verified` под рукой мера считается заново, не из
    # frontmatter, — на честной статье результат обязан совпасть.
    v_verified = verify.check(out_path, mirror, mirror, conn, result["проверено"])
    assert v_verified["ок"], v_verified["проблемы"]
    assert v_verified["источники_без_цитаты"] == []


def test_honest_article_with_unused_fact_still_passes_but_reports_it(mirror, conn, tmp_path):
    """Неиспользованный (но честный) факт — не подделка, `ок` не должен
    стать `False` из-за него; спека §6 требует ИЗМЕРЯТЬ долю, не отвергать
    статью за неё."""
    raw = [
        {"источник": "Тема 1#Пост 100",
         "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр трубок"},
        {"источник": "FAQ 100#Ответ",
         "цитата": "Рекомендуемый интервал замены масла 5000 км пробега", "суть": "интервал масла"},
    ]
    result = facts.check_all(raw, mirror, conn)
    assert result["статистика"]["отброшено"] == 0, result["отброшено"]

    draft = "Тормозные трубки — 3/16 дюйма[^f1].\n"
    meta = {"заголовок": "Статья с хвостом", "собрано": "2026-08-22"}
    text = articles.render(draft, result["проверено"], meta)
    out_path = tmp_path / "статья.md"
    out_path.write_text(text, encoding="utf-8")

    v = verify.check(out_path, mirror, mirror, conn)
    assert v["ок"], v["проблемы"]
    assert v["источники_без_цитаты"] == ["f2"]

    v_verified = verify.check(out_path, mirror, mirror, conn, result["проверено"])
    assert v_verified["ок"], v_verified["проблемы"]
    assert v_verified["источники_без_цитаты"] == ["f2"]


# --- Н6 ре-ревью: мера охвата не является проверкой, если верить frontmatter


def test_tampered_unused_facts_field_is_caught_when_verified_is_given(mirror, conn, tmp_path):
    """Живая находка ревью (F4): снять строку `неиспользованные_факты` из
    frontmatter — и мера молча показывает ноль, хотя факт реально не
    использован. С `verified` под рукой это уже не измерение, а проверка."""
    raw = [
        {"источник": "Тема 1#Пост 100",
         "цитата": "Трубки нужны 3/16 дюйма", "суть": "диаметр трубок"},
        {"источник": "FAQ 100#Ответ",
         "цитата": "Рекомендуемый интервал замены масла 5000 км пробега", "суть": "интервал масла"},
    ]
    result = facts.check_all(raw, mirror, conn)
    text = ("---\ntype: статья\nисточников: 2\nсобрано: 2026-08-22\n---\n\n"
            "# Зазоры\n\nТормозные трубки — 3/16 дюйма[^f1].\n\n"
            "## Сноски\n\n[^f1]: «Трубки нужны 3/16 дюйма» — Razum, 11.10.2014, "
            "[[Тема 1#Пост 100]]\n")
    out_path = tmp_path / "статья.md"
    out_path.write_text(text, encoding="utf-8")

    without_verified = verify.check(out_path, mirror, mirror, conn)
    assert without_verified["ок"], without_verified["проблемы"]
    assert without_verified["источники_без_цитаты"] == [], (
        "без verified проверка не может знать про снятую строку — не должна выдумывать ответ")

    with_verified = verify.check(out_path, mirror, mirror, conn, result["проверено"])
    assert not with_verified["ок"]
    assert any("неиспользованные_факты" in p for p in with_verified["проблемы"])
    assert with_verified["источники_без_цитаты"] == ["f2"]


def test_inflated_sources_count_is_caught_when_verified_is_given(mirror, conn, tmp_path):
    """Живая находка ревью (F5): `источников: 99` при одной сноске проходит
    без `verified` — задача 5 отдельно чинила это завышение (F6/F6-бис) в
    `articles.render`, но гейт задачи 6 его не сторожил вовсе."""
    raw = [{"источник": "Тема 1#Пост 100", "цитата": "Трубки нужны 3/16 дюйма", "суть": "х"}]
    result = facts.check_all(raw, mirror, conn)
    text = ("---\ntype: статья\nисточников: 99\nсобрано: 2026-08-22\n---\n\n"
            "# Зазоры\n\nТормозные трубки — 3/16 дюйма[^f1].\n\n"
            "## Сноски\n\n[^f1]: «Трубки нужны 3/16 дюйма» — Razum, 11.10.2014, "
            "[[Тема 1#Пост 100]]\n")
    out_path = tmp_path / "статья.md"
    out_path.write_text(text, encoding="utf-8")

    result_check = verify.check(out_path, mirror, mirror, conn, result["проверено"])
    assert not result_check["ок"]
    assert any("источников" in p for p in result_check["проблемы"])


# --- замечание тимлида (ре-ревью соседа): цитата в статье нормализована по
# пробелам, сверять её с телом источника нужно ЧЕРЕЗ ТУ ЖЕ нормализацию --


def test_multiline_quote_survives_render_and_verify_roundtrip(mirror, conn, tmp_path):
    """Живой случай: в источнике `12 - Коробка передач` и `В: механическая
    5-ти ступенчатая» — два отдельных абзаца одного поста (настоящий
    перенос строки, не подделка — Global Constraint фазы №1). Цитата
    факта несёт этот перенос дословно; `articles._footnote_line` схлопывает
    его в один пробел при сборке (F2 ревью задачи 5) — статья на диске уже
    НЕ побайтово то, что лежит в заметке-источнике. `verify.check` обязан
    сравнивать цитату из статьи с телом источника через ту же нормализацию
    (`notes.normalize_spaces`, делегировано `facts.check_one`), а не искать
    подстроку буквально — иначе КАЖДАЯ такая многострочная цитата дала бы
    ложное «дословно не найдено»."""
    raw = [{"источник": "Тема 2#Пост 200",
            "цитата": "12 - Коробка передач\n\nВ: механическая 5-ти ступенчатая",
            "суть": "12-й символ VIN — коробка передач"}]
    result = facts.check_all(raw, mirror, conn)
    assert result["статистика"]["отброшено"] == 0, result["отброшено"]

    draft = "Двенадцатый символ VIN кодирует коробку передач[^f1].\n"
    meta = {"заголовок": "Проверка переноса строки", "собрано": "2026-08-22"}
    text = articles.render(draft, result["проверено"], meta)
    # Сама сборка уже схлопнула перенос в один пробел — контрольная
    # проверка, что тест действительно воспроизводит живой случай (перенос
    # ушёл ИЗ ЦИТАТЫ), а не тестирует вырожденный ввод.
    assert "передач\n\nВ:" not in text
    assert "передач В:" in text

    out_path = tmp_path / "статья.md"
    out_path.write_text(text, encoding="utf-8")
    v = verify.check(out_path, mirror, mirror, conn)
    assert v["ок"], v["проблемы"]
