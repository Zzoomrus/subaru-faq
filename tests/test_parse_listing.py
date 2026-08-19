from pathlib import Path

from pipeline import parse_listing

FIX = Path(__file__).parent / "fixtures" / "list_19_1.html"
FIX_BROKEN_ROW = Path(__file__).parent / "fixtures" / "list_12_1.html"


def _html() -> str:
    return FIX.read_bytes().decode("cp1251", "replace")


def _html_broken_row() -> str:
    return FIX_BROKEN_ROW.read_bytes().decode("cp1251", "replace")


def test_parses_rows():
    rows = parse_listing.parse(_html())
    assert len(rows) >= 10
    r = rows[0]
    assert r.tid > 0 and r.fid == 19
    assert r.title and r.author
    assert r.replies >= 0 and r.views >= 0
    assert r.pages >= 1


def test_started_at_is_iso_date():
    rows = parse_listing.parse(_html())
    assert all(len(r.started_at) == 10 and r.started_at[4] == "-" for r in rows if r.started_at)


def test_malformed_container_row_is_skipped_not_misparsed():
    # В list_12_1.html не хватает закрывающего </tr>, из-за чего и lxml, и
    # html.parser вкладывают ~35 соседних строк ВНУТРЬ одного <tr>. Если это
    # не отбросить, select_one внутри такого контейнера подхватывает чужие
    # ячейки: TID=15537 (реально replies=8397/views=2838025/pages=420)
    # ловил чужие replies=2669/views=1155788 от TID=27731 (у которого своё
    # правильное значение — pages=134). Каждая тема должна встретиться
    # РОВНО ОДИН раз (контейнер отброшен) со своими подлинными числами.
    rows = parse_listing.parse(_html_broken_row())
    by_tid = {}
    for r in rows:
        by_tid.setdefault(r.tid, []).append(r)

    assert len(by_tid.get(27731, [])) == 1
    r27731 = by_tid[27731][0]
    assert (r27731.pages, r27731.replies, r27731.views) == (134, 2669, 1155788)

    assert len(by_tid.get(15537, [])) == 1
    r15537 = by_tid[15537][0]
    assert (r15537.pages, r15537.replies, r15537.views) == (420, 8397, 2838025)
