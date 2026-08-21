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
from pathlib import Path

import pytest

from pipeline import attachments, db, fetch_assets, mirror, mirror_faq, run

# Тот же фикстурный файл, что уже использует `test_mirror_faq`/`test_anchor_
# contract` (URL `.../upload/blog/84b/x.jpg`) — не заводим новый бинарник
# только для того, чтобы у FAQ и блога была общая картинка.
FIX_ASSETS = Path(__file__).parent / "fixtures" / "faq_assets"


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


def test_extension_follows_the_bytes_not_the_url(tmp_path):
    """Ruling 38: `<hash>.php` для JPEG механически цело — файл есть, вставка
    не битая, `check` молчит, — но Obsidian такую вставку картинкой не
    покажет, то есть 50 настоящих фотографий не существуют для читателя.
    Тип определяется по магическим байтам при копировании.
    """
    jpeg = b"\xff\xd8\xff" + b"\x00" * 40
    url = "http://subaru-faq.ru/bitrix/components/bitrix/forum.interface/show_file.php?fid=6252"
    assert attachments.asset_name(url).endswith(".php")            # без байтов — как раньше
    assert attachments.asset_name(url, jpeg).endswith(".jpg")      # с байтами — по типу
    # Хэш (то есть тождество файла) от расширения не зависит: меняется только
    # хвост имени, адрес остаётся тем же ключом.
    assert attachments.asset_name(url).split(".")[0] == attachments.asset_name(url, jpeg).split(".")[0]

    dest = tmp_path / "assets"
    dest.mkdir()
    src = tmp_path / "raw"
    src.write_bytes(jpeg)
    assert mirror.copy_asset(url, src, dest).endswith(".jpg")


def test_unrecognized_bytes_keep_the_extension_from_the_path():
    # Условие лида: не опознались байты — оставляем расширение из адреса.
    # Молча назвать неизвестное `.jpg` хуже, чем оставить как есть.
    garbage = b"\x00\x01\x02\x03" + "это не формат".encode() * 4
    assert attachments.sniff_extension(garbage) is None
    assert attachments.asset_name("http://h/a.jpg", garbage).endswith(".jpg")
    assert attachments.asset_name("http://h/getfile?id=7", garbage).endswith(".bin")


def test_ambiguous_container_signatures_do_not_guess():
    # `PK\x03\x04` — это и .zip, и .docx/.xlsx/.pptx; OLE2 — и .doc, и .xls.
    # Такие сигнатуры опознаются как ДОКУМЕНТ (для проверки содержимого при
    # доборе), но расширения не дают: угадывание тут хуже адреса.
    zip_head = b"PK\x03\x04" + b"\x00" * 20
    ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 20
    for data in (zip_head, ole2):
        assert attachments.is_document(data)
        assert attachments.sniff_extension(data) is None
        assert attachments.asset_name("http://h/f.doc", data).endswith(".doc")


def test_signature_knowledge_lives_in_one_place():
    # M5: раньше знание о сигнатурах было в двух местах и разошлось (мёртвая
    # константа не знала про WEBP, живой код знал). Пробы добора обязаны быть
    # тем же кодом, а не копией.
    assert fetch_assets._looks_like_image is attachments.is_image
    assert fetch_assets._looks_like_document is attachments.is_document
    webp = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 20
    assert fetch_assets._looks_like_image(webp)
    assert attachments.sniff_extension(webp) == ".webp"


def _db_with_faq_and_blog_sharing_one_image(tmp_path):
    """FAQ и блог ссылаются на ОДНУ и ту же картинку архива Ф0/Ф1 (URL
    фикстуры `FIX_ASSETS`) — сценарий, из-за которого до Ruling 37 90
    картинок жили в вики дважды: 108 лишних копий, 7,68 МиБ.
    """
    conn = db.connect(tmp_path / "shared.sqlite")
    db.init_schema(conn)
    url = "http://subaru-faq.ru/upload/blog/84b/x.jpg"
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md) VALUES "
                 "('bitrix', 1, 'вопрос', 'ответ ![](%s)')" % url)
    conn.execute("INSERT INTO faq_images(engine, nr, url) VALUES ('bitrix', 1, ?)", (url,))
    conn.execute("INSERT INTO blog_posts(blog, post_id, title, body_md, tags, is_excerpt, truncated) "
                 "VALUES ('remont', 1, 'запись', 'тело ![](%s)', '[]', 0, 0)" % url)
    conn.execute("INSERT INTO blog_images(blog, post_id, comment_id, url) VALUES ('remont', 1, NULL, ?)",
                 (url,))
    conn.commit()
    return conn


def test_all_sections_share_one_asset_directory(tmp_path):
    """Один адрес — один файл на всю вики.

    До этой правки FAQ и блоги копировали общие картинки каждый себе: 108
    лишних копий на 7,68 МиБ. Хуже копий то, что статья Ф3 стала бы третьим
    каталогом, и один адрес получил бы три файла с одним именем.

    Бриф задачи предполагал точку сборки `run.build_mirror(conn, root)` без
    путей к архиву картинок — на практике их пришлось передать явно
    (дефолты `run.build_mirror` указывают на боевые `data/...`, а не на
    `tmp_path`, и звать генератор с боевыми путями внутри теста нельзя).
    """
    conn = _db_with_faq_and_blog_sharing_one_image(tmp_path)

    root = tmp_path / "Источники"
    run.build_mirror(conn, root,
                      archive_assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                      archive_assets_root=FIX_ASSETS / "assets")

    assert (root / "assets").is_dir()
    assert not (root / "FAQ" / "assets").exists()
    assert not (root / "Блоги" / "assets").exists()

    names = sorted(p.name for p in (root / "assets").iterdir())
    assert len(names) == len(set(names))
    assert len(names) == 1          # общая картинка лежит ровно одним файлом


def test_prune_keeps_files_used_by_another_section(tmp_path):
    """Сирота — файл, не нужный НИКОМУ, а не «не нужный этому разделу».

    При общем каталоге прежнее правило снесло бы картинки FAQ на прогоне
    форума и наоборот, а следующая перегенерация вернула бы их — вечная
    churn с виду пустым результатом.
    """
    root = tmp_path / "Источники"
    assets_dir = root / "assets"
    assets_dir.mkdir(parents=True)
    name = attachments.asset_name("http://h/shared.jpg")
    (assets_dir / name).write_bytes(b"shared bytes")

    # Заметка FAQ ссылается на файл; форумный прогон о нём ничего не знает
    # (`used=set()`) — ровно так выглядит `used_assets` форума, когда
    # картинка вообще не его, а FAQ.
    faq_dir = root / "FAQ"
    faq_dir.mkdir(parents=True)
    (faq_dir / "FAQ 1.md").write_text("![[assets/%s]]" % name, encoding="utf-8")

    # notes_written=1 — форумный прогон что-то написал (иначе уборка не
    # запускается вовсе, это отдельный предохранитель).
    removed = mirror.prune_assets(assets_dir, set(), 1)

    assert removed == 0
    assert (assets_dir / name).exists()
