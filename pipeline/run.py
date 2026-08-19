"""Точка входа конвейера: `python -m pipeline.run <команда>`.

Пока прогон существовал только как heredoc в документе, документ и
реальность расходились при первой же правке кода. Следующая фаза — это
повторные прогоны (добор картинок, перегенерация зеркала, проверка), им
нужна команда, а не рецепт.

Команды:

    ingest    разобрать сырые страницы в SQLite (`--rebuild` — с нуля)
    coverage  отчёт покрытия в CSV + сводка в stdout
    mirror    сгенерировать зеркало `wiki/Источники`
    check     проверка целостности всей вики (код возврата 1 при находках)
    all       всё перечисленное подряд

Порядок в `all` не случаен: `ingest_sections` обязан отработать до
генерации заметок, иначе в каждой заметке пустое поле «раздел».

ВАЖНО про `--rebuild`. Загрузчик идемпотентен — повторный прогон не портит
базу, — но это НЕ значит, что он подхватит правку парсеров: `upsert_post`
обновляет пост, только если новый `text` длиннее сохранённого (а снятие
мусора делает текст короче), а вложения уже виденной страницы не
переразбираются вовсе. После любой правки `parse_*`/`html_text` базу надо
пересоздать: `python -m pipeline.run all --rebuild` (~95 с на полном
архиве).
"""
import argparse
import sys
from pathlib import Path

from pipeline import check_mirror, coverage, db, ingest, mirror

DEFAULT_PAGES = Path("data/raw/archive/pages")
DEFAULT_MANIFEST = Path("data/raw/archive/manifest.jsonl")
DEFAULT_DB = Path("data/forum.sqlite")
DEFAULT_CSV = Path("data/coverage.csv")
DEFAULT_WIKI = Path("wiki")
DEFAULT_MIRROR_DIR = "Источники"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pipeline.run",
        description="Конвейер subaru-faq: сырой HTML архива -> SQLite -> зеркало Obsidian.")
    p.add_argument("command", choices=["ingest", "coverage", "mirror", "check", "all"])
    p.add_argument("--pages", type=Path, default=DEFAULT_PAGES,
                   help="каталог сырых страниц архива (по умолчанию %s)" % DEFAULT_PAGES)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                   help="manifest.jsonl краулера (провенанс: url, снимок)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="файл SQLite")
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="куда писать отчёт покрытия")
    p.add_argument("--wiki", type=Path, default=DEFAULT_WIKI,
                   help="корень вики: зеркало и статьи следующей фазы")
    p.add_argument("--mirror-dir", default=DEFAULT_MIRROR_DIR,
                   help="подкаталог вики для заметок-источников")
    p.add_argument("--rebuild", action="store_true",
                   help="снести базу перед загрузкой — единственный способ "
                        "применить правку парсеров")
    return p


def _drop_db(path: Path) -> None:
    """Удаляет базу вместе со спутниками WAL-режима: `-wal` без основного
    файла — это несогласованный хвост прошлого прогона.
    """
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cmd = args.command
    mirror_path = args.wiki / args.mirror_dir
    rc = 0

    if cmd in ("ingest", "coverage", "mirror", "all"):
        if args.rebuild and cmd in ("ingest", "all"):
            _drop_db(args.db)
            print("база пересоздана с нуля: %s" % args.db)
        conn = db.connect(args.db)
        db.init_schema(conn)

    if cmd in ("ingest", "all"):
        print("разделов:", ingest.ingest_sections(args.pages, conn))
        print("загрузка:", ingest.ingest_all(args.pages, args.manifest, conn))

    if cmd in ("coverage", "all"):
        rows = coverage.report(conn)
        coverage.to_csv(rows, args.csv)
        print("покрытие:", coverage.summary(rows), "->", args.csv)

    if cmd in ("mirror", "all"):
        print("заметок:", mirror.write_all(conn, mirror_path), "->", mirror_path)

    if cmd in ("check", "all"):
        found = check_mirror.check(args.wiki)
        print("целостность:", {k: len(v) for k, v in found.items()})
        for key, items in found.items():
            for item in items[:20]:
                print("  %s: %s" % (key, item))
            if len(items) > 20:
                print("  %s: ... ещё %d" % (key, len(items) - 20))
        if any(found.values()):
            rc = 1

    return rc


if __name__ == "__main__":
    sys.exit(main())
