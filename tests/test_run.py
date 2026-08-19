import json
import sqlite3
from pathlib import Path

from pipeline import run

FIX = Path(__file__).parent / "fixtures"
NAMES = ["read_19_10045_1.html", "read_20_31559_2.html", "index_1.html"]


def _archive(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    for n in NAMES:
        (pages / n).write_bytes((FIX / n).read_bytes())
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("\n".join(
        json.dumps({"key": n, "file": n, "url": "http://subaru-faq.ru/" + n,
                    "ts": "20150419142404"}) for n in NAMES), encoding="utf-8")
    return pages, manifest


def _args(tmp_path, *cmd):
    pages, manifest = _archive(tmp_path)
    return [*cmd, "--pages", str(pages), "--manifest", str(manifest),
            "--db", str(tmp_path / "forum.sqlite"),
            "--csv", str(tmp_path / "coverage.csv"),
            "--wiki", str(tmp_path / "wiki"),
            "--mirror-dir", "Источники"]


def test_all_runs_the_whole_pipeline(tmp_path):
    # Единственная точка входа: следующая фаза состоит из повторных прогонов,
    # heredoc в документе для этого не годится.
    assert run.main(_args(tmp_path, "all")) == 0
    assert (tmp_path / "forum.sqlite").exists()
    assert (tmp_path / "coverage.csv").exists()
    assert (tmp_path / "wiki" / "Источники" / "Тема 10045.md").exists()


def test_rebuild_recreates_the_database_from_scratch(tmp_path):
    # I7: правку парсеров подхватывает ТОЛЬКО пересоздание базы —
    # у команды должен быть явный способ это сделать.
    args = _args(tmp_path, "ingest", "--rebuild")
    assert run.main(args) == 0
    db_path = tmp_path / "forum.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO posts(mid, tid, page_no, text) VALUES (1, 1, 1, 'мусор')")
    conn.commit(); conn.close()
    assert run.main(args) == 0
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM posts WHERE mid = 1").fetchone()[0] == 0


def test_check_reports_findings_and_exit_code(tmp_path):
    # Проверка целостности должна ГОВОРИТЬ ненулевым кодом возврата, иначе
    # её нельзя поставить в конец прогона и уйти.
    wiki = tmp_path / "wiki" / "Источники"
    wiki.mkdir(parents=True)
    (wiki / "Тема 1.md").write_text("[[Тема 404]]\n", encoding="utf-8")
    assert run.main(["check", "--wiki", str(tmp_path / "wiki")]) == 1
    (wiki / "Тема 1.md").write_text("чисто\n", encoding="utf-8")
    assert run.main(["check", "--wiki", str(tmp_path / "wiki")]) == 0


def test_check_walks_the_whole_wiki_not_only_the_mirror(tmp_path):
    # Проверять надо всё дерево вики: статьи следующей фазы ссылаются на
    # источники, и обе стороны должны попадать в один проход.
    wiki = tmp_path / "wiki"
    (wiki / "Источники").mkdir(parents=True)
    (wiki / "Статьи" / "Тормоза").mkdir(parents=True)
    (wiki / "Источники" / "Тема 1.md").write_text("##### Пост 100\n\nа\n", encoding="utf-8")
    (wiki / "Статьи" / "Тормоза" / "Суппорт.md").write_text(
        "[[Тема 1#Пост 100]] и [[Тема 1#Пост 999]]\n", encoding="utf-8")
    assert run.main(["check", "--wiki", str(wiki)]) == 1
