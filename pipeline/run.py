"""Точка входа конвейера: `python -m pipeline.run <команда>`.

Пока прогон существовал только как heredoc в документе, документ и
реальность расходились при первой же правке кода. Следующая фаза — это
повторные прогоны (добор картинок, перегенерация зеркала, проверка), им
нужна команда, а не рецепт.

Команды:

    ingest        разобрать сырые страницы в SQLite (`--rebuild` — с нуля)
    coverage      отчёт покрытия в CSV + сводка в stdout
    mirror        сгенерировать зеркало `wiki/Источники`
    check         проверка целостности всей вики (код возврата 1 при находках)
    all           всё перечисленное подряд
    assets index    добор Ф2: индексация CDX (тела не тянет, ~40 мин на 6008 URL)
    assets download добор Ф2: скачивание тел там, где индексация нашла снимок

Порядок в `all` не случаен: `ingest_sections` обязан отработать до
генерации заметок, иначе в каждой заметке пустое поле «раздел».

`assets` — отдельная пара команд (`assets index`, затем `assets download`),
намеренно не входящая в `all`: прогон на всём списке — это часы работы, его
запускают вручную и с сервера (см. `global-constraints.md` фазы Ф2 про
токен-бакет Wayback), а не при каждом обычном прогоне конвейера. `sync_to_db`
(запись найденного в `attachments`) вызывается ровно один раз — после того,
как вся команда отработала, а не внутри цикла по URL: у Python предупреждения
с одинаковым текстом из одного места кода показываются один раз за процесс,
и повторные вызовы `sync_to_db` в цикле создали бы у предупреждений о
повреждённом манифесте ложное впечатление, что проблема исчезла.

Базу создаёт только загрузчик (`ingest`/`all`). Для `coverage`/`mirror`
отсутствующая база — ошибка (код 2), а не пустой результат: молча созданная
пустая база означала «0 заметок» и снос всего зеркала как осиротевшего при
нулевом коде возврата. Второй рубеж — предохранитель в `mirror.write_all`
(удалений не может быть больше, чем записей).

ВАЖНО про `--rebuild`. Загрузчик идемпотентен — повторный прогон не портит
базу, — но это НЕ значит, что он подхватит правку парсеров: `upsert_post`
обновляет пост, только если новый `text` длиннее сохранённого (а снятие
мусора делает текст короче), а вложения уже виденной страницы не
переразбираются вовсе. После любой правки `parse_*`/`html_text` базу надо
пересоздать: `python -m pipeline.run all --rebuild` (~85 с на полном
архиве).
"""
import argparse
import logging
import sys
from pathlib import Path

from pipeline import assets_state, check_mirror, coverage, db, fetch_assets, ingest, mirror

DEFAULT_PAGES = Path("data/raw/archive/pages")
DEFAULT_MANIFEST = Path("data/raw/archive/manifest.jsonl")
DEFAULT_DB = Path("data/forum.sqlite")
DEFAULT_CSV = Path("data/coverage.csv")
DEFAULT_WIKI = Path("wiki")
DEFAULT_MIRROR_DIR = "Источники"
DEFAULT_ASSETS_MANIFEST = Path("data/assets/manifest.jsonl")
DEFAULT_ASSETS_ROOT = Path("data/assets/files")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pipeline.run",
        description="Конвейер subaru-faq: сырой HTML архива -> SQLite -> зеркало Obsidian.")
    p.add_argument("command", choices=["ingest", "coverage", "mirror", "check", "all", "assets"])
    p.add_argument("assets_action", nargs="?", choices=["index", "download"], default=None,
                   help="для command=assets: index — индексация CDX, download — скачивание")
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
    p.add_argument("--assets-manifest", type=Path, default=DEFAULT_ASSETS_MANIFEST,
                   help="манифест добора Ф2 (по умолчанию %s)" % DEFAULT_ASSETS_MANIFEST)
    p.add_argument("--assets-root", type=Path, default=DEFAULT_ASSETS_ROOT,
                   help="куда класть скачанные файлы (по умолчанию %s)" % DEFAULT_ASSETS_ROOT)
    p.add_argument("--limit", type=int, default=None,
                   help="ограничить число URL за прогон (для проб/тестов)")
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
    # Прогон добора идёт часами на сервере под nohup, лог — единственный
    # свидетель. basicConfig поднимает уровень до INFO, чтобы в лог попадали
    # периодические отметки прогресса fetch_assets (без него процесс часами
    # молчит, и "жив или висит" не отличить до самого конца). captureWarnings
    # — чтобы предупреждения о повреждённом манифесте (warnings.warn в
    # assets_state) шли туда же, а не улетали мимо лога.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.captureWarnings(True)
    args = _parser().parse_args(argv)
    cmd = args.command

    if cmd == "assets":
        if args.assets_action is None:
            print("укажи действие: assets index | assets download")
            return 2
        conn = db.connect(args.db)
        db.init_schema(conn)
        if args.assets_action == "index":
            stats = fetch_assets.index_pending(conn, args.assets_manifest, limit=args.limit)
            print("индексация:", stats)
        else:
            stats = fetch_assets.download(conn, args.assets_manifest, args.assets_root, limit=args.limit)
            print("скачивание:", stats)
        # Один раз по завершении всего прогона, не в цикле по URL — см.
        # докстринг модуля про предупреждения "once per process".
        sync_stats = assets_state.sync_to_db(conn, args.assets_manifest, args.assets_root)
        print("синхронизация с базой:", sync_stats)
        return 0

    mirror_path = args.wiki / args.mirror_dir
    rc = 0

    if cmd in ("ingest", "coverage", "mirror", "all"):
        if args.rebuild and cmd in ("ingest", "all"):
            _drop_db(args.db)
            print("база пересоздана с нуля: %s" % args.db)
        if cmd in ("coverage", "mirror") and not args.db.exists():
            # Создавать базу на лету — обязанность загрузчика, а не
            # подкоманд чтения: для них отсутствующая база значит
            # пропущенный шаг загрузки или опечатку в `--db`, а не «нечего
            # генерировать». Молча созданная пустая база давала «заметок: 0»
            # и код возврата 0 — при том, что зеркало при этом сносилось.
            print("база не найдена: %s (загрузите архив: "
                  "python -m pipeline.run ingest)" % args.db)
            return 2
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
        try:
            print("заметок:", mirror.write_all(conn, mirror_path), "->", mirror_path)
        except RuntimeError as e:
            # Предохранитель генератора: база не описывает это зеркало.
            # Печатаем причину без трейсбека и уходим с ненулевым кодом.
            print("ОШИБКА:", e)
            return 2

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
