"""Тесты отчёта покрытия (задача 6).

Формула брифа `COALESCE(replies_expected, 0) + 1` неверна: у 1612 тем
(созданных фолбэком `ensure_thread_from_page`, см. `pipeline.ingest`)
`replies_expected IS NULL`, потому что темы нет ни в одном оглавлении —
"ожидание 1 пост" для них было бы ложью, а не отсутствием данных.
Поэтому отчёт делит темы на пять групп, а не на четыре счётчика брифа:

- `ok`           — тема из оглавления, `got == expected`;
- `short`        — тема из оглавления, `got < expected` (и got > 0);
- `extra`        — тема из оглавления, `got > expected`;
- `missing`      — тема из оглавления, постов вообще нет (`got == 0`);
- `unverifiable` — `replies_expected IS NULL`, сверять не с чем.

Приоритет классификации: `unverifiable` проверяется первым (нет `expected`
— неважно, сколько постов), затем `missing` (`got == 0`), затем знак `diff`.
На реальных данных `unverifiable` и `missing` не пересекаются (фолбэк
создаёт строку `threads` только когда у страницы есть хотя бы один пост —
см. `ingest.ensure_thread_from_page`), но порядок проверок закладывает это
как инвариант, а не как случайное совпадение.
"""
from pipeline import db, coverage


def _seed(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    db.init_schema(conn)
    threads = [
        (1, 19, "полная", 2),        # 3 поста ожидается (2+1), 3 есть -> ok
        (2, 19, "неполная", 5),      # 6 ожидается, 1 есть -> short
        (3, 19, "пустая", 1),        # 2 ожидается, 0 есть -> missing
        (4, 19, "с довеском", 1),    # 2 ожидается, 3 есть -> extra
        (5, 19, "без оглавления", None),  # replies_expected NULL -> unverifiable
    ]
    for tid, fid, title, replies_expected in threads:
        conn.execute(
            "INSERT INTO threads(tid, fid, title, replies_expected) VALUES (?,?,?,?)",
            (tid, fid, title, replies_expected))
    posts = [
        (10, 1), (11, 1), (12, 1),   # тема 1: 3 поста
        (20, 2),                     # тема 2: 1 пост
        (30, 4), (31, 4), (32, 4),   # тема 4: 3 поста
        (40, 5),                     # тема 5: 1 пост, но нечем сверить
    ]
    for mid, tid in posts:
        conn.execute("INSERT INTO posts(mid, tid, page_no, text) VALUES (?,?,1,'x')", (mid, tid))
    conn.commit()
    return conn


def test_report_flags_groups_and_diff(tmp_path):
    rows = {r.tid: r for r in coverage.report(_seed(tmp_path))}

    assert rows[1].group == "ok"
    assert rows[1].expected == 3
    assert rows[1].got == 3
    assert rows[1].diff == 0

    assert rows[2].group == "short"
    assert rows[2].diff == -5

    assert rows[3].group == "missing"
    assert rows[3].got == 0
    assert rows[3].expected == 2
    assert rows[3].diff == -2

    assert rows[4].group == "extra"
    assert rows[4].diff == 1

    assert rows[5].group == "unverifiable"
    assert rows[5].expected is None
    assert rows[5].diff is None
    assert rows[5].got == 1


def test_summary_counts(tmp_path):
    s = coverage.summary(coverage.report(_seed(tmp_path)))
    assert s == {
        "threads": 5,
        "ok": 1,
        "short": 1,
        "extra": 1,
        "missing": 1,
        "unverifiable": 1,
    }


def test_null_expected_thread_with_zero_posts_is_unverifiable_not_missing(tmp_path):
    # Инвариант из docstring модуля: на реальных данных такого не бывает
    # (фолбэк создаёт threads только когда у страницы есть посты), но
    # классификация не должна путать "нечем сверить" с "постов нет" —
    # приоритет unverifiable выше missing.
    conn = db.connect(tmp_path / "t2.sqlite")
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO threads(tid, fid, title, replies_expected) VALUES (6, 19, 'без постов и без оглавления', NULL)")
    conn.commit()
    rows = coverage.report(conn)
    assert len(rows) == 1
    assert rows[0].group == "unverifiable"
    assert rows[0].got == 0


def test_to_csv_includes_group_column(tmp_path):
    rows = coverage.report(_seed(tmp_path))
    out = tmp_path / "coverage.csv"
    coverage.to_csv(rows, out)
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert "group" in header.split(",")
