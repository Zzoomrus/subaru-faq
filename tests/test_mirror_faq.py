from pathlib import Path

import yaml

from pipeline import db, mirror_faq

FIX_ASSETS = Path(__file__).parent / "fixtures" / "faq_assets"


def _frontmatter(md: str) -> dict:
    lines = md.split("\n")
    assert lines[0] == "---"
    end = next(i for i in range(1, len(lines)) if lines[i] == "---")
    return yaml.safe_load("\n".join(lines[1:end]))


def _seed(tmp_path, name="t.sqlite"):
    conn = db.connect(tmp_path / name)
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO faq(engine, nr, catnr, prog, category, question, answer_md, source_url, snapshot_ts) "
        "VALUES ('bitrix', 502, NULL, 'Субару в общем', 'Субару в общем › Модельный ряд', "
        "'Субару Леон - Subaru Leone (1971-1994)', 'Первая линейка ![](http://subaru-faq.ru/upload/blog/84b/x.jpg) моделей.', "
        "'http://www.subaru-faq.ru/faq/index.php?ELEMENT_ID=502', '20110109125532')")
    conn.execute(
        "INSERT INTO faq_images(engine, nr, url, local_path) VALUES "
        "('bitrix', 502, 'http://subaru-faq.ru/upload/blog/84b/x.jpg', NULL)")
    conn.execute(
        "INSERT INTO faq(engine, nr, catnr, prog, category, question, answer_md, source_url, snapshot_ts) "
        "VALUES ('old', 11, 1, 'COMMON', 'Общая информация о Субару', "
        "'Чем отличаются Legacy и Outback ?', 'Legacy Outback - одна из комплектаций.', "
        "'http://www.subaru-faq.ru/faq/faq.php?display=faq&nr=11&catnr=1&prog=COMMON&lang=ru', '20070726215648')")
    conn.execute(
        "INSERT INTO faq(engine, nr, catnr, prog, category, question, answer_md, source_url, snapshot_ts) "
        "VALUES ('old', 42, 14, 'DRIVE', 'Категория', "
        "'Вопрос без картинки', 'Ответ с ![](http://subaru-faq.ru/upload/blog/dead/gone.jpg) утраченной картинкой.', "
        "'http://www.subaru-faq.ru/faq/faq.php?display=faq&nr=42&catnr=14&prog=DRIVE&lang=ru', '20070726220143')")
    conn.execute(
        "INSERT INTO faq_images(engine, nr, url, local_path) VALUES "
        "('old', 42, 'http://subaru-faq.ru/upload/blog/dead/gone.jpg', NULL)")
    conn.commit()
    return conn


def test_bitrix_note_name_and_frontmatter(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "FAQ"
    mirror_faq.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                          assets_root=FIX_ASSETS / "assets")
    md = (out / "FAQ 502.md").read_text(encoding="utf-8")
    fm = _frontmatter(md)
    assert fm["номер"] == 502
    assert fm["движок"] == "bitrix"
    assert fm["prog"] == "Субару в общем"
    assert fm["адрес"] == "http://www.subaru-faq.ru/faq/index.php?ELEMENT_ID=502"
    assert fm["снимок"] == "20110109125532"
    assert fm["aliases"] == ["Субару Леон - Subaru Leone (1971-1994)"]
    assert "## Вопрос" in md and "## Ответ" in md
    assert "Субару Леон - Subaru Leone (1971-1994)" in md


def test_old_engine_note_gets_disambiguated_filename(tmp_path):
    # nr=11 существует и в старом движке, и потенциально в Bitrix (реальная
    # коллизия номеров на живом корпусе — см. task-6-report.md) — старый
    # движок ВСЕГДА получает отдельное пространство имён, а не только при
    # обнаруженной коллизии (устойчивость сносок при доборе новых записей).
    conn = _seed(tmp_path)
    out = tmp_path / "FAQ"
    mirror_faq.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                          assets_root=FIX_ASSETS / "assets")
    assert (out / "FAQ старый 11.md").exists()
    assert not (out / "FAQ 11.md").exists()


def test_found_image_is_copied_and_embedded(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "FAQ"
    mirror_faq.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                          assets_root=FIX_ASSETS / "assets")
    md = (out / "FAQ 502.md").read_text(encoding="utf-8")
    assert "![[" in md
    assert "не сохранилось" not in md
    copied = list((out / "assets").glob("*.jpg"))
    assert len(copied) == 1
    assert copied[0].read_bytes() == b"fake-jpg-bytes"


def test_missing_image_gets_loss_note_not_broken_embed(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "FAQ"
    mirror_faq.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                          assets_root=FIX_ASSETS / "assets")
    md = (out / "FAQ старый 42.md").read_text(encoding="utf-8")
    assert "изображение не сохранилось" in md
    assert "![[" not in md


def test_title_mismatch_adds_second_alias(tmp_path):
    # Задача 6, ревизия по дефекту: заголовок темы Bitrix (`title`), когда он
    # расходится с настоящим вопросом (`question`, уже очищенным парсером от
    # меток "Вопрос:"/"Ответ:" — см. parse_faq), не должен теряться — он
    # уходит во второй алиас, а не пропадает из заметки вовсе.
    conn = _seed(tmp_path)
    conn.execute(
        "INSERT INTO faq(engine, nr, catnr, prog, category, question, answer_md, source_url, snapshot_ts, title) "
        "VALUES ('bitrix', 103, NULL, 'Субару - ездим.', 'Буксировка и использование прицепа', "
        "'Не вредно ли на машине с АКПП буксировать прицеп?', "
        "'На автомобилях с АКПП допускается такая же буксировка, как и на механике.', "
        "'http://www.subaru-faq.ru/faq/index.php?ELEMENT_ID=103', '20100404023158', "
        "'Рекомендации по использованию прицепов на автомобилях с АКПП')")
    conn.commit()
    out = tmp_path / "FAQ"
    mirror_faq.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                          assets_root=FIX_ASSETS / "assets")
    md = (out / "FAQ 103.md").read_text(encoding="utf-8")
    fm = _frontmatter(md)
    assert fm["aliases"] == [
        "Не вредно ли на машине с АКПП буксировать прицеп?",
        "Рекомендации по использованию прицепов на автомобилях с АКПП",
    ]
    assert "Не вредно ли на машине с АКПП буксировать прицеп?" in md.split("## Ответ")[0]
    assert "Вопрос:" not in md and "Ответ:" not in md.split("## Ответ")[1]


def test_write_all_removes_stale_notes_but_not_foreign_files(tmp_path):
    conn = _seed(tmp_path)
    out = tmp_path / "FAQ"
    out.mkdir(parents=True)
    (out / "FAQ 999.md").write_text("устаревшая", encoding="utf-8")
    (out / "не наша заметка.md").write_text("чужой файл", encoding="utf-8")
    n = mirror_faq.write_all(conn, out, assets_manifest=FIX_ASSETS / "manifest-assets.jsonl",
                              assets_root=FIX_ASSETS / "assets")
    assert n == 3
    assert not (out / "FAQ 999.md").exists()
    assert (out / "не наша заметка.md").exists()


def test_duplicate_entry_is_marked_and_points_to_canonical(tmp_path):
    """Дубль обязан быть виден в заметке, а не только в базе.

    Иначе исполнитель Ф3, читающий вики глазами, сошлётся на старую запись
    как на самостоятельный источник.
    """
    conn = db.connect(tmp_path / "m.sqlite")
    db.init_schema(conn)
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md, answer_text) "
                 "VALUES ('bitrix', 42, 'Про масло', 'Полусинтетика.', 'Полусинтетика.')")
    conn.execute("INSERT INTO faq(engine, nr, question, answer_md, answer_text, "
                 "duplicate_of_engine, duplicate_of_nr) "
                 "VALUES ('old', 7, 'Про масло', 'Полусинтетика.', 'Полусинтетика.', 'bitrix', 42)")
    conn.commit()

    out = tmp_path / "FAQ"
    mirror_faq.write_all(conn, out)

    dup = (out / "FAQ старый 7.md").read_text(encoding="utf-8")
    assert "дубль_чего: \"[[FAQ 42]]\"" in dup
    assert "> [!warning] Дубль" in dup
    assert "[[FAQ 42]]" in dup

    canon = (out / "FAQ 42.md").read_text(encoding="utf-8")
    assert "дубль_чего" not in canon
    assert "[!warning]" not in canon
