from pipeline import check_mirror


def _note(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _file(root, rel, content=b"\xff\xd8\xff"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def test_detects_broken_link_and_broken_heading_anchor(tmp_path):
    _note(tmp_path, "Тема 1.md",
          "##### Пост 100\n\nтекст\n\nсм. [[Тема 2#Пост 999]] и [[Тема 404#Пост 1]]\n")
    _note(tmp_path, "Тема 2.md", "##### Пост 200\n\nдругой\n")
    res = check_mirror.check(tmp_path)
    assert "Тема 404" in " ".join(res["broken_links"])
    assert "Пост 999" in " ".join(res["broken_anchors"])


def test_heading_anchor_link_is_actually_checked(tmp_path):
    # I6: прежняя регулярка не матчила `[[Тема N#Заголовок]]` вовсе — ссылка
    # молча не проверялась, и отсутствие находок было неотличимо от
    # отсутствия проверки. После перехода на заголовочные якоря это
    # основной вид ссылок в проекте.
    _note(tmp_path, "Статья.md", "[[Тема 1#Пост 100]]\n")
    _note(tmp_path, "Тема 1.md", "##### Пост 100\n\nтекст\n")
    assert check_mirror.check(tmp_path) == {
        "broken_links": [], "broken_anchors": [], "duplicate_anchors": [], "broken_embeds": []}


def test_block_anchor_links_still_supported(tmp_path):
    # Блочные якоря генератор больше не ставит, но проверка обязана уметь
    # оба вида: статьи Сергея могут ссылаться и так.
    _note(tmp_path, "Тема 1.md", "текст ^p100\n\n[[Тема 2#^p200]] и [[Тема 2#^p999]]\n")
    _note(tmp_path, "Тема 2.md", "другой ^p200\n")
    res = check_mirror.check(tmp_path)
    assert res["broken_links"] == []
    assert any("^p999" in a for a in res["broken_anchors"])


def test_walks_subdirectories_and_keys_by_relative_path(tmp_path):
    # Спека кладёт статьи в `Статьи/Тормоза/`, источники — в `Источники/`.
    # Плоский glob объявлял бы все ссылки на источники битыми.
    _note(tmp_path, "Источники/Тема 1.md", "##### Пост 100\n\nтекст\n")
    _note(tmp_path, "Статьи/Тормоза/Суппорт.md",
          "по имени [[Тема 1#Пост 100]] и по пути [[Источники/Тема 1#Пост 100]]\n")
    assert check_mirror.check(tmp_path)["broken_links"] == []
    assert check_mirror.check(tmp_path)["broken_anchors"] == []


def test_same_stem_in_different_folders_does_not_collapse(tmp_path):
    # При рекурсии ключ по имени файла схлопнул бы две разные заметки в одну
    # и якорь одной считался бы якорем другой.
    _note(tmp_path, "Источники/Тема 1.md", "##### Пост 100\n\nтекст\n")
    _note(tmp_path, "Черновики/Тема 1.md", "##### Пост 777\n\nчерновик\n")
    _note(tmp_path, "Статья.md", "[[Источники/Тема 1#Пост 777]]\n")
    res = check_mirror.check(tmp_path)
    assert any("Пост 777" in a for a in res["broken_anchors"]), \
        "якорь чужой заметки не должен считаться существующим"


def test_frontmatter_is_not_scanned_for_links(tmp_path):
    # Отложенная находка №9: `[[` экранируется только в теле поста, а в
    # заголовке темы (фронтматтер) — нет. Ссылки ищем только в теле.
    _note(tmp_path, "Тема 1.md",
          '---\ntid: 1\naliases: ["Тема про [[скобки]] в названии"]\n---\n\nтекст\n')
    assert check_mirror.check(tmp_path)["broken_links"] == []


def test_frontmatter_is_cut_by_closing_line_not_by_substring(tmp_path):
    # Ruling 25: у четырёх тем `---` стоит ВНУТРИ названия. Наивный поиск
    # подстроки обрезал бы фронтматтер по середине значения — и половина
    # тела осталась бы непроверенной.
    _note(tmp_path, "Тема 1.md",
          '---\ntid: 1\naliases: ["2010/03/13 --- ТАНКОДРОМ НИИ 21"]\n---\n\n'
          'тело со ссылкой [[Тема 404]]\n')
    assert any("Тема 404" in b for b in check_mirror.check(tmp_path)["broken_links"])


def test_detects_duplicate_block_anchor_and_duplicate_heading(tmp_path):
    # Задвоенный якорь любого вида ломает адресацию молча: ссылка ведёт на
    # первое вхождение, а автор сноски имел в виду другое.
    _note(tmp_path, "Тема 1.md",
          "первый ^p100\n\nвторой, ошибочно с тем же якорем ^p100\n\n"
          "##### Пост 500\n\nа\n\n##### Пост 500\n\nб\n")
    res = check_mirror.check(tmp_path)
    joined = " ".join(res["duplicate_anchors"])
    assert "^p100" in joined
    assert "Пост 500" in joined


def test_clean_mirror_has_no_findings(tmp_path):
    _note(tmp_path, "Источники/Тема 1.md", "##### Пост 100\n\nа\n")
    _note(tmp_path, "Источники/Тема 2.md", "##### Пост 200\n\nб\n\n[[Тема 1#Пост 100]]\n")
    assert check_mirror.check(tmp_path) == {
        "broken_links": [], "broken_anchors": [], "duplicate_anchors": [], "broken_embeds": []}


def test_embed_to_existing_file_is_not_flagged_but_broken_link_is(tmp_path):
    # Находка задачи 4: генератор зеркала вставляет картинки как
    # `![[путь]]` — прежняя LINK-регулярка не отличала `![[...]]` от
    # `[[...]]` и резолвила вставку как ссылку на заметку, которой нет.
    # Ссылка на несуществующую заметку рядом ДОЛЖНА остаться в
    # broken_links — регрессия здесь была бы «стали слепы к вставкам вообще».
    _note(tmp_path, "Тема 1.md",
          "##### Пост 100\n\nсмотри ![[assets/host/abc.jpg]] и заодно [[Тема 404]]\n")
    _file(tmp_path, "assets/host/abc.jpg")
    res = check_mirror.check(tmp_path)
    assert res["broken_links"] == ["Тема 1 -> [[Тема 404]]"]
    assert res["broken_embeds"] == []


def test_embed_to_missing_file_is_flagged_as_broken_embed_not_broken_link(tmp_path):
    _note(tmp_path, "Тема 1.md", "##### Пост 100\n\n![[assets/host/missing.jpg]]\n")
    res = check_mirror.check(tmp_path)
    assert res["broken_links"] == []
    assert any("assets/host/missing.jpg" in e for e in res["broken_embeds"])


def test_embed_resolves_by_filename_when_path_does_not_match_exactly(tmp_path):
    # Как и для ссылок на заметки, Obsidian резолвит вставку по имени
    # файла, если точный путь не совпал (заведомое приближение, см.
    # docstring модуля про by_name).
    _note(tmp_path, "Тема 1.md", "##### Пост 100\n\n![[abc.jpg]]\n")
    _file(tmp_path, "assets/host/abc.jpg")
    assert check_mirror.check(tmp_path)["broken_embeds"] == []


# --- alias-индекс (задача 6 Ф3, ре-ревью Н12/Н14) ---------------------------


def test_parse_aliases_reads_single_alias():
    text = '---\ntid: 1\naliases: ["Провалы в работе ДВС"]\n---\n\n# Тема 1\n'
    assert check_mirror.parse_aliases(text) == ["Провалы в работе ДВС"]


def test_parse_aliases_reads_multiple_and_unescapes_quotes_and_backslashes():
    # Форма, которой `mirror._yaml_dquote` реально экранирует: `\\` первым,
    # `"` вторым — разбор обязан развернуть это в исходную строку.
    text = ('---\naliases: ["Вопрос со знаком \\"кавычки\\"", "Путь C:\\\\Temp"]'
            '\n---\n\nbody')
    assert check_mirror.parse_aliases(text) == ['Вопрос со знаком "кавычки"', "Путь C:\\Temp"]


def test_parse_aliases_ignores_the_word_outside_frontmatter():
    text = '---\ntid: 1\n---\n\nПост цитирует "aliases: [подделка]" внутри текста.\n'
    assert check_mirror.parse_aliases(text) == []


def test_parse_aliases_returns_empty_list_when_absent():
    assert check_mirror.parse_aliases("---\ntid: 1\n---\n\nbody") == []


def test_build_alias_index_is_case_insensitive():
    notes = {"Тема 42753": '---\naliases: ["Провалы в работе ДВС"]\n---\n\nbody'}
    index = check_mirror.build_alias_index(notes)
    assert index["провалы в работе двс"] == ["Тема 42753"]
    assert "Провалы в работе ДВС".casefold() in index


def test_build_alias_index_collects_all_notes_sharing_one_alias():
    # Живой замер ре-ревью: 116 alias уже неоднозначны сами по себе (один
    # заголовок у нескольких заметок).
    notes = {
        "Тема 1": '---\naliases: ["Освещение"]\n---\n\nbody',
        "Тема 2": '---\naliases: ["Освещение"]\n---\n\nbody',
    }
    index = check_mirror.build_alias_index(notes)
    assert sorted(index["освещение"]) == ["Тема 1", "Тема 2"]
