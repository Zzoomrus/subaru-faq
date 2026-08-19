from pathlib import Path

from pipeline import parse_listing

FIX = Path(__file__).parent / "fixtures" / "list_19_1.html"


def _html() -> str:
    return FIX.read_bytes().decode("cp1251", "replace")


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
