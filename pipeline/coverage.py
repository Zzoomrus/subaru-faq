"""Отчёт покрытия: сколько постов темы сохранилось в архиве против того,
сколько ожидалось по оглавлению форума.

Формула брифа задачи 6 (`COALESCE(replies_expected, 0) + 1`) неверна для
1612 тем, у которых `replies_expected IS NULL` — тема отсутствует во всех
собранных оглавлениях (не сохранилась страница листинга, либо тема
пропала из списка к моменту снятия оглавления Wayback), а строка в
`threads` создана фолбэком `ingest.ensure_thread_from_page` со страницы
темы. Для таких тем "ожидание 1 пост" было бы ложью: сверять не с чем,
а не "сошлось на пустом множестве".

Поэтому темы делятся на пять непересекающихся групп:

- `unverifiable` — `replies_expected IS NULL`, сверка невозможна;
- `missing`      — тема из оглавления, но постов не сохранилось вовсе
                    (`got == 0`);
- `ok`           — тема из оглавления, `got == expected`;
- `short`        — тема из оглавления, `got < expected` (и `got > 0`);
- `extra`        — тема из оглавления, `got > expected`.

Приоритет проверок в `_classify`: сначала `unverifiable` (нет `expected`
— неважно, сколько постов), потом `missing` (`got == 0`), потом знак
`diff`. На реальном корпусе `unverifiable` и `missing` не пересекаются
(фолбэк создаёт строку `threads` только когда у страницы есть хотя бы
один пост), но порядок проверок делает это утверждение инвариантом кода,
а не случайным совпадением данных.
"""
import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Row:
    tid: int
    fid: int
    title: str
    expected: int | None
    got: int
    diff: int | None
    group: str


def _classify(expected: int | None, got: int) -> tuple[int | None, str]:
    if expected is None:
        return None, "unverifiable"
    diff = got - expected
    if got == 0:
        return diff, "missing"
    if diff == 0:
        return diff, "ok"
    if diff < 0:
        return diff, "short"
    return diff, "extra"


def report(conn) -> list[Row]:
    sql = """
    SELECT t.tid, t.fid, t.title, t.replies_expected,
           (SELECT COUNT(*) FROM posts p WHERE p.tid = t.tid) AS got
    FROM threads t ORDER BY t.fid, t.tid
    """
    rows = []
    for tid, fid, title, replies_expected, got in conn.execute(sql):
        expected = None if replies_expected is None else replies_expected + 1
        diff, group = _classify(expected, got)
        rows.append(Row(tid, fid, title, expected, got, diff, group))
    return rows


def summary(rows: list[Row]) -> dict[str, int]:
    return {
        "threads": len(rows),
        "ok": sum(1 for r in rows if r.group == "ok"),
        "short": sum(1 for r in rows if r.group == "short"),
        "extra": sum(1 for r in rows if r.group == "extra"),
        "missing": sum(1 for r in rows if r.group == "missing"),
        "unverifiable": sum(1 for r in rows if r.group == "unverifiable"),
    }


def to_csv(rows: list[Row], path: Path) -> None:
    """Пишет отчёт в CSV с BOM: самый вероятный способ его посмотреть —
    открыть в Excel, а Excel на русской Windows без BOM читает UTF-8 как
    кракозябры.
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["tid", "fid", "title", "expected", "got", "diff", "group"])
        for r in rows:
            w.writerow([
                r.tid, r.fid, r.title,
                "" if r.expected is None else r.expected,
                r.got,
                "" if r.diff is None else r.diff,
                r.group,
            ])
