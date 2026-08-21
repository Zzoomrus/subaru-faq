from pipeline import db, faq_dedup


def _faq_with_dup(conn, engine, nr, question, answer, dup_engine, dup_nr):
    conn.execute(
        "INSERT INTO faq(engine, nr, question, answer_md, answer_text, "
        "duplicate_of_engine, duplicate_of_nr) VALUES (?,?,?,?,?,?,?)",
        (engine, nr, question, answer, answer, dup_engine, dup_nr),
    )


def _faq(conn, engine, nr, question, answer):
    conn.execute(
        "INSERT INTO faq(engine, nr, question, answer_md, answer_text) VALUES (?,?,?,?,?)",
        (engine, nr, question, answer, answer),
    )


def test_normalize_question_ignores_case_punctuation_and_spacing():
    a = faq_dedup.normalize_question("Какое масло лить в EJ20?")
    b = faq_dedup.normalize_question("какое  масло лить в ej20")
    assert a == b


def test_finds_duplicate_by_question(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite")
    db.init_schema(conn)
    _faq(conn, "bitrix", 42, "Какое масло лить в EJ20?", "Полусинтетику 10W-40.")
    _faq(conn, "old", 7, "какое масло лить в ej20", "Полусинтетику.")
    conn.commit()

    dupes = faq_dedup.find_duplicates(conn)

    assert len(dupes) == 1
    assert dupes[0]["engine"] == "old" and dupes[0]["nr"] == 7
    assert dupes[0]["canonical_engine"] == "bitrix" and dupes[0]["canonical_nr"] == 42
    assert dupes[0]["reason"] == "вопрос совпал"


def test_old_engine_is_never_canonical(tmp_path):
    """Битриксовая запись полнее: у неё есть категория и она новее.

    Канон всегда bitrix — иначе сноски пилота указывали бы то на один
    движок, то на другой в зависимости от порядка обхода.
    """
    conn = db.connect(tmp_path / "d.sqlite")
    db.init_schema(conn)
    _faq(conn, "old", 7, "Вопрос", "Ответ старого движка")
    _faq(conn, "bitrix", 42, "Вопрос", "Ответ старого движка и ещё абзац")
    conn.commit()

    dupes = faq_dedup.find_duplicates(conn)

    assert [(d["engine"], d["canonical_engine"]) for d in dupes] == [("old", "bitrix")]


def test_finds_duplicate_by_answer_containment_when_question_differs(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite")
    db.init_schema(conn)
    _faq(conn, "bitrix", 42, "Про масло",
         "Лить полусинтетику 10W-40 и менять раз в 7000 км. "
         "Такой интервал прописан заводским регламентом.")
    _faq(conn, "old", 7, "Масло — что лить",
         "Лить полусинтетику 10W-40 и менять раз в 7000 км.")
    conn.commit()

    dupes = faq_dedup.find_duplicates(conn)

    assert len(dupes) == 1
    assert dupes[0]["reason"] == "ответ дословно внутри канонического"


def test_apply_clears_stale_pointer_when_record_no_longer_matches(tmp_path):
    """apply() обязан сбросить мусорную пометку, а не только проставить новую.

    Находка ревью: без строки `UPDATE ... SET duplicate_of_* = NULL` перед
    пересчётом весь набор тестов оставался зелёным — регрессия (запись
    перестала быть дублем, а пометка осталась) прошла бы незамеченной.
    Запись здесь по текущим правилам НЕ дубль (другой вопрос, короткий,
    не совпадающий по тексту ответ), но заранее помечена мусорным указателем.
    """
    conn = db.connect(tmp_path / "d.sqlite")
    db.init_schema(conn)
    _faq(conn, "bitrix", 42, "Вопрос про масло", "Полусинтетика.")
    _faq_with_dup(conn, "old", 7, "Совсем другой вопрос про фильтры",
                  "Другой ответ.", "bitrix", 999999)
    conn.commit()

    faq_dedup.apply(conn)

    row = conn.execute(
        "SELECT duplicate_of_engine, duplicate_of_nr FROM faq WHERE engine = 'old' AND nr = 7"
    ).fetchone()
    assert row == (None, None)


def test_short_answer_does_not_count_as_containment(tmp_path):
    """«Да.» встречается внутри чего угодно — это не признак дубля."""
    conn = db.connect(tmp_path / "d.sqlite")
    db.init_schema(conn)
    _faq(conn, "bitrix", 42, "Про масло", "Да. Лить полусинтетику 10W-40 и менять раз в 7000 км.")
    _faq(conn, "old", 7, "Совсем другой вопрос", "Да.")
    conn.commit()

    assert faq_dedup.find_duplicates(conn) == []


def test_answer_containment_ignores_whitespace_differences(tmp_path):
    """Два движка форума разбивают абзацы ответа по-разному.

    Находка ревью на боевых данных: `FAQ старый 155` («антенна») и
    `FAQ старый 114` («давление E-4AT») — тот же текст, что у канонических
    `FAQ 140`/`FAQ 168`, но с одинарным `\n` там, где у Bitrix `\n\n`, и с
    двойными пробелами. Точное посимвольное `in` это пропускало.
    """
    conn = db.connect(tmp_path / "d.sqlite")
    db.init_schema(conn)
    _faq(conn, "bitrix", 42, "Про антенну",
         "Первый абзац про антенну и её механизм выдвижения из корпуса машины.\n\n"
         "Второй абзац про смазку и уход, чтобы механизм не закисал со временем.")
    _faq(conn, "old", 7, "Совсем другой вопрос про антенну",
         "Первый абзац про антенну и её механизм выдвижения из корпуса машины.\n"
         "Второй абзац  про смазку и уход, чтобы механизм не закисал  со временем.")
    conn.commit()

    dupes = faq_dedup.find_duplicates(conn)

    assert len(dupes) == 1
    assert dupes[0]["reason"] == "ответ дословно внутри канонического"
