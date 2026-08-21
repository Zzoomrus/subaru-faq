"""Имя файла вложения и уборка осиротевших файлов.

M4 + M3 + отложенный пункт 6 итогового ревью Ф2. Три утверждения, каждое
куплено кровью:

1. имя считает ОДНА функция на все разделы зеркала и на добор — иначе один
   файл получает разные имена в разных каталогах (было: 90 картинок в двух);
2. в ключ имени ОБЯЗАТЕЛЬНО входит строка запроса — вложения форума
   раздаются адресами `show_file.php?fid=N`, где путь один на все файлы
   (замер на боевой базе: 49 разных файлов на одном пути);
3. осиротевшие файлы убираются, но только свои и только когда заметки
   действительно записаны.
"""
import pytest

from pipeline import attachments, db, fetch_assets, mirror, mirror_faq


def test_one_naming_rule_for_the_mirror_and_for_the_downloader():
    url = "http://s017.radikal.ru/i416/1308/40/2b6f4aa67490.jpg"
    name = attachments.asset_name(url)
    assert mirror_faq._local_asset_name(url) == name
    # У добора своя РАСКЛАДКА на диске (каталог по хосту), но то же имя.
    assert fetch_assets.local_name(url) == "s017.radikal.ru/" + name


def test_query_string_is_part_of_the_key():
    # Главная опасность правки: вложения форума раздаются одним путём, а
    # различает их только номер в запросе. Ключ без запроса схлопнул бы 49
    # разных файлов боевой базы в одно имя — молча.
    base = "http://subaru-faq.ru/bitrix/components/bitrix/forum.interface/show_file.php"
    assert attachments.asset_name(base + "?fid=1") != attachments.asset_name(base + "?fid=2")
    assert attachments.asset_name(base + "?fid=1") != attachments.asset_name(base)


def test_the_same_file_gets_the_same_name_despite_www_scheme_and_encoding():
    variants = ["http://www.subaru-faq.ru/upload/blog/cda/8.jpg",
                "http://subaru-faq.ru/upload/blog/cda/8.jpg",
                "https://SUBARU-FAQ.ru/upload/blog/cda/8.jpg",
                "http://subaru-faq.ru/upload/blog/cda/8%2Ejpg"]
    assert len({attachments.asset_name(u) for u in variants}) == 1


def test_extension_comes_from_the_path_and_falls_back_to_bin():
    assert attachments.asset_name("http://h/a.JPG").endswith(".jpg")
    assert attachments.asset_name("http://h/getfile?id=7").endswith(".bin")
    assert attachments.asset_name("http://h/a.verylongext").endswith(".bin")


def test_copy_asset_refuses_to_overwrite_different_bytes(tmp_path):
    # Совпадение имени при разном содержимом = либо коллизия ключа, либо
    # потерянная различающая часть адреса. Молчать нельзя: подставленная в
    # заметку чужая картинка не ловится ни проверкой целостности, ни диффом.
    dest = tmp_path / "assets"
    dest.mkdir()
    src_a = tmp_path / "a.jpg"; src_a.write_bytes(b"AAA")
    src_b = tmp_path / "b.jpg"; src_b.write_bytes(b"BBB")
    url = "http://h/pic.jpg"
    assert mirror.copy_asset(url, src_a, dest) == "assets/%s" % attachments.asset_name(url)
    # тот же адрес и то же содержимое — повтор молча ничего не делает
    assert mirror.copy_asset(url, src_a, dest).startswith("assets/")
    with pytest.raises(RuntimeError, match="коллизия имени файла вложения"):
        mirror.copy_asset(url, src_b, dest)


def _forum_db(tmp_path):
    conn = db.connect(tmp_path / "a.sqlite")
    db.init_schema(conn)
    conn.execute("INSERT INTO sections(fid, title) VALUES (19, 'Раздел')")
    conn.execute("INSERT INTO threads(tid, fid, title, author, started_at, replies_expected, views) "
                 "VALUES (1, 19, 'Тема', 'a', '2007-01-01', 0, 1)")
    conn.execute("INSERT INTO posts(mid, tid, page_no, author, posted_at, number, markdown, text) "
                 "VALUES (10, 1, 1, 'a', '2007-01-01 00:00:00', '#1', 'вот ![](http://h/x.jpg) всё', 'x')")
    conn.execute("INSERT INTO attachments(mid, kind, url, local_path, status) "
                 "VALUES (10, 'external_image', 'http://h/x.jpg', 'h/старое-имя.jpg', 'ok')")
    conn.commit()
    return conn


def test_write_all_removes_orphaned_asset_files(tmp_path):
    # M3: уборка заметок была, уборки файлов не было ни у одного генератора —
    # «git diff пуст» держался только на накоплении. Правка имени (M4) разом
    # осиротила бы 1859 файлов.
    conn = _forum_db(tmp_path)
    assets_root = tmp_path / "files"
    (assets_root / "h").mkdir(parents=True)
    (assets_root / "h" / "старое-имя.jpg").write_bytes(b"bytes")
    out = tmp_path / "Источники"
    out.mkdir()
    (out / "assets").mkdir()
    # то, что осталось от прошлого прогона с другой формулой имени
    (out / "assets" / "0123456789abcdef.jpg").write_bytes("мёртвый".encode())
    # чужой файл человека — не наш вид имени, не трогаем
    (out / "assets" / "схема из письма.png").write_bytes("чужой".encode())

    mirror.write_all(conn, out, assets_root=assets_root)
    names = sorted(p.name for p in (out / "assets").iterdir())
    assert names == sorted([attachments.asset_name("http://h/x.jpg"), "схема из письма.png"])


def test_prune_does_nothing_when_no_notes_were_written(tmp_path):
    # Предохранитель: заметок ноль — каталог не трогается вовсе (пустая или
    # чужая база). Обычный предохранитель «удалений не больше, чем записей»
    # здесь не годится: при переименовании удалений заведомо больше.
    dest = tmp_path / "assets"
    dest.mkdir()
    (dest / "0123456789abcdef.jpg").write_bytes(b"x")
    assert mirror.prune_assets(dest, set(), 0) == 0
    assert (dest / "0123456789abcdef.jpg").exists()
    assert mirror.prune_assets(dest, set(), 1) == 1
    assert not (dest / "0123456789abcdef.jpg").exists()
