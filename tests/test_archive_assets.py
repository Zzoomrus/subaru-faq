"""Отражение архива Ф0/Ф1 в базе: `faq_images.local_path`/`blog_images.local_path`.

Находка ре-ревью: колонка была NULL у ВСЕХ строк — 0 из 232 у FAQ, 0 из 437 у
блогов, — хотя в вики стояли 105 + 296 настоящих вставок. Зеркало находило
файл через манифест архива, а колонку не заполнял никто и никогда. Исполнитель
Ф3 спросил бы базу «какие картинки уцелели», получил бы ноль при 401 уцелевшей
и решил бы, что добор провалился. Тот же класс, что уже кусал фазу (`assets_
state.sync_to_db` не звался при пересборке — все вложения форума числились
утраченными), и та же развязка: диск — истина, база — отражение, отражение
восстанавливается при каждой загрузке.

Главное утверждение файла — последний тест: база и вики отвечают ОДНО И ТО ЖЕ,
потому что считаются одной функцией (`archive_assets.find`).
"""
import json
from pathlib import Path

from pipeline import archive_assets, db, mirror_blog, mirror_faq


def _archive(tmp_path, *rels, missing_on_disk=()):
    """Манифест архива + файлы. `missing_on_disk` — путь есть в манифесте, а
    файла нет: манифест и диск расходятся, и это не теория (тот же довод, что
    в `assets_state.sync_to_db`, где `ok` без файла становится `lost`).
    """
    root = tmp_path / "archive"
    manifest = tmp_path / "manifest-assets.jsonl"
    lines = []
    for rel in (*rels, *missing_on_disk):
        if rel not in missing_on_disk:
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"\xff\xd8\xff" + rel.encode()[:8] + b"\x00" * 32)
        lines.append(json.dumps({"path": rel, "url": "http://subaru-faq.ru/" + rel,
                                  "ts": "20110109125532", "bytes": 43}, ensure_ascii=False))
    root.mkdir(parents=True, exist_ok=True)
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest, root


def _db(tmp_path):
    conn = db.connect(tmp_path / "a.sqlite")
    db.init_schema(conn)
    return conn


def test_find_requires_both_the_manifest_and_the_file():
    index = {"upload/blog/84b/x.jpg"}
    root = Path("/несуществующий")
    assert archive_assets.find("http://h/upload/blog/84b/x.jpg", index, root) is None   # нет на диске
    assert archive_assets.find("http://h/upload/other.jpg", index, root) is None        # нет в манифесте


def test_normalize_path_ignores_host_case_encoding_and_double_slashes():
    n = archive_assets.normalize_path
    assert n("http://www.subaru-faq.ru/upload/blog/bcc//p1000089.jpg") == "upload/blog/bcc/p1000089.jpg"
    assert n("https://subaru-faq.ru/upload/blog/84b/x%20y.jpg") == "upload/blog/84b/x y.jpg"


def test_sync_fills_local_path_for_survivors_and_nulls_the_rest(tmp_path):
    manifest, root = _archive(tmp_path, "upload/blog/aaa/live.jpg",
                              missing_on_disk=("upload/blog/bbb/promised.jpg",))
    conn = _db(tmp_path)
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md) VALUES ('bitrix', 1, 'в', 'о')")
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES "
                 "('bitrix', 1, 'http://www.subaru-faq.ru/upload/blog/aaa/live.jpg')")
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES "
                 "('bitrix', 1, 'http://subaru-faq.ru/upload/blog/bbb/promised.jpg')")
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES "
                 "('bitrix', 1, 'http://чужой.хост/фото.jpg')")
    conn.execute("INSERT INTO blog_images(blog, post_id, comment_id, url) VALUES "
                 "('remont', 1, 5, 'http://subaru-faq.ru/upload/blog/aaa/live.jpg')")
    conn.commit()

    stats = archive_assets.sync_local_paths(conn, manifest, root)
    assert stats == {"faq_ok": 1, "faq_lost": 2, "blog_ok": 1, "blog_lost": 0}
    rows = dict(conn.execute("SELECT url, local_path FROM faq_images").fetchall())
    assert rows["http://www.subaru-faq.ru/upload/blog/aaa/live.jpg"] == "upload/blog/aaa/live.jpg"
    assert rows["http://subaru-faq.ru/upload/blog/bbb/promised.jpg"] is None
    assert rows["http://чужой.хост/фото.jpg"] is None
    # Картинка комментария — такая же строка таблицы, синхронизируется вместе
    # со всеми (M1: у неё непустой `comment_id`).
    assert conn.execute("SELECT local_path FROM blog_images WHERE comment_id = 5").fetchone()[0] \
        == "upload/blog/aaa/live.jpg"


def test_sync_is_idempotent_and_clears_a_vanished_file(tmp_path):
    manifest, root = _archive(tmp_path, "upload/blog/aaa/live.jpg")
    conn = _db(tmp_path)
    conn.execute("INSERT INTO blog_images(blog, post_id, url) VALUES "
                 "('remont', 1, 'http://subaru-faq.ru/upload/blog/aaa/live.jpg')")
    conn.commit()
    assert archive_assets.sync_local_paths(conn, manifest, root)["blog_ok"] == 1
    assert archive_assets.sync_local_paths(conn, manifest, root)["blog_ok"] == 1

    (root / "upload/blog/aaa/live.jpg").unlink()
    stats = archive_assets.sync_local_paths(conn, manifest, root)
    assert stats["blog_ok"] == 0 and stats["blog_lost"] == 1
    # NULL пишется ЯВНО: иначе исчезнувший файл остался бы «уцелевшим» навсегда.
    assert conn.execute("SELECT local_path FROM blog_images").fetchone()[0] is None


def test_the_database_answer_matches_the_wiki_exactly(tmp_path):
    """Главное утверждение: «уцелела ли картинка» по базе и наличие вставки в
    заметке — один и тот же ответ, потому что считаются одной функцией.
    """
    manifest, root = _archive(tmp_path, "upload/blog/aaa/faq.jpg", "upload/blog/bbb/entry.jpg",
                              "upload/blog/ccc/comment.jpg",
                              missing_on_disk=("upload/blog/ddd/gone.jpg",))
    faq_ok = "http://www.subaru-faq.ru/upload/blog/aaa/faq.jpg"
    entry_ok = "http://subaru-faq.ru/upload/blog/bbb/entry.jpg"
    comment_ok = "http://subaru-faq.ru/upload/blog/ccc/comment.jpg"
    gone = "http://subaru-faq.ru/upload/blog/ddd/gone.jpg"

    conn = _db(tmp_path)
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md) VALUES "
                 "('bitrix', 1, 'в', 'ответ ![](%s) и ![](%s)')" % (faq_ok, gone))
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES ('bitrix', 1, ?)", (faq_ok,))
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES ('bitrix', 1, ?)", (gone,))
    conn.execute("INSERT INTO blog_posts(blog, post_id, title, body_md, tags, is_excerpt, truncated) "
                 "VALUES ('remont', 1, 'з', 'тело ![](%s)', '[]', 0, 0)" % entry_ok)
    conn.execute("INSERT INTO blog_images(blog, post_id, comment_id, url) VALUES ('remont', 1, NULL, ?)",
                 (entry_ok,))
    conn.execute("INSERT INTO blog_comments(blog, post_id, comment_id, parent_id, depth, author, "
                 "posted_at, text_md) VALUES ('remont', 1, 5, NULL, 0, 'a', 'д', 'вот ![](%s)')" % comment_ok)
    conn.execute("INSERT INTO blog_images(blog, post_id, comment_id, url) VALUES ('remont', 1, 5, ?)",
                 (comment_ok,))
    conn.commit()

    archive_assets.sync_local_paths(conn, manifest, root)
    wiki = tmp_path / "wiki"
    mirror_faq.write_all(conn, wiki / "FAQ", assets_manifest=manifest, assets_root=root)
    mirror_blog.write_all(conn, wiki / "Блоги", assets_manifest=manifest, assets_root=root)

    in_db = q = conn.execute(
        "SELECT count(*) FROM (SELECT local_path FROM faq_images WHERE local_path IS NOT NULL "
        "UNION ALL SELECT local_path FROM blog_images WHERE local_path IS NOT NULL)").fetchone()[0]
    embeds = sum(p.read_text(encoding="utf-8").count("![[assets/") for p in wiki.rglob("*.md"))
    losses = sum(p.read_text(encoding="utf-8").count("изображение не сохранилось")
                 for p in wiki.rglob("*.md"))
    assert in_db == embeds == 3
    assert losses == 1
    assert q == 3
