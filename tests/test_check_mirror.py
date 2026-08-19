from pipeline import check_mirror


def _note(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
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
        "broken_links": [], "broken_anchors": [], "duplicate_anchors": []}


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
        "broken_links": [], "broken_anchors": [], "duplicate_anchors": []}
