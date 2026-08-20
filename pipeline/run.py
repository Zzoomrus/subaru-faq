"""Точка входа конвейера: `python -m pipeline.run <команда>`.

Пока прогон существовал только как heredoc в документе, документ и
реальность расходились при первой же правке кода. Следующая фаза — это
повторные прогоны (добор картинок, перегенерация зеркала, проверка), им
нужна команда, а не рецепт.

Команды:

    ingest        разобрать сырые страницы в SQLite (`--rebuild` — с нуля;
                  включает и форум, и FAQ — см. `faq` ниже)
    coverage      отчёт покрытия в CSV + сводка в stdout
    mirror        сгенерировать зеркало `wiki/Источники` (форум + FAQ)
    check         проверка целостности всей вики (код возврата 1 при находках)
    all           всё перечисленное подряд
    faq [load|mirror]  FAQ отдельно от полного прогона: load — только разбор
                       сырых страниц раздела (`--site-root`/`--site-manifest`)
                       в таблицы `faq`/`faq_images`, mirror — только заметки
                       в `<--wiki>/<--mirror-dir>/FAQ/`, без действия — оба
                       (тот же код, что и внутри `ingest`/`mirror`/`all` —
                       для точечного повтора без полного форумного прогона)
    assets index    добор Ф2: индексация CDX (тела не тянет, ~40 мин на 6008 URL)
    assets download добор Ф2: скачивание тел там, где индексация нашла снимок
    site build <faq|blogs>  добор Ф2 задача 5: план скачивания раздела по CDX,
                            сохраняется на диск (`--site-root`), CDX спрашивается
                            один раз за весь прогон (см. `fetch_site.py`)
    site fetch <faq|blogs>  скачивание раздела по уже сохранённому плану,
                            идемпотентно (манифест `--site-manifest`)

Порядок в `all` не случаен: `ingest_sections` обязан отработать до
генерации заметок, иначе в каждой заметке пустое поле «раздел».

**FAQ (ревизия задачи 6):** до этой правки таблица `faq` и её колонка
`title` появлялись на диске только через ручной `ALTER TABLE` — `ingest`/
`all --rebuild` пересоздавали схему БЕЗ FAQ, и «снёс базу и собрал заново —
получил ровно то же» было ложью для этого раздела. Теперь загрузка/
генерация FAQ живёт и внутри `ingest`/`mirror`/`all` (автоматически, из
уже скачанных `data/raw/site/faq/`), и отдельной командой `faq` — для
случая, когда нужно перегенерировать только FAQ, не трогая форум (посты —
это минуты работы на полном архиве, а правка одного FAQ-парсера не должна
требовать полного `ingest`).

`assets` — отдельная пара команд (`assets index`, затем `assets download`),
намеренно не входящая в `all`: прогон на всём списке — это часы работы, его
запускают вручную и с сервера (см. `global-constraints.md` фазы Ф2 про
токен-бакет Wayback), а не при каждом обычном прогоне конвейера. `sync_to_db`
(запись найденного в `attachments`) вызывается ровно один раз — после того,
как вся команда отработала, а не внутри цикла по URL: у Python предупреждения
с одинаковым текстом из одного места кода показываются один раз за процесс,
и повторные вызовы `sync_to_db` в цикле создали бы у предупреждений о
повреждённом манифесте ложное впечатление, что проблема исчезла.

`site` — по той же причине вне `all` и разбита на `build`/`fetch`: `build`
дешёвый (один запрос CDX на раздел) и сохраняет план на диск НАВСЕГДА, а не
только в памяти процесса — суточный прогон `fetch` может оборваться и
перезапуститься много раз, и каждый такой перезапуск обязан читать уже
сохранённый план, а не спрашивать CDX заново (см. `fetch_site.save_plan`).
`site` не трогает `forum.sqlite` вовсе — план-построение сайта не о базе,
разбор скачанных страниц в записи — работа следующей задачи фазы.

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

from pipeline import (assets_state, check_mirror, coverage, db, fetch_assets, fetch_site, ingest, mirror,
                      mirror_faq, parse_faq)

DEFAULT_PAGES = Path("data/raw/archive/pages")
DEFAULT_MANIFEST = Path("data/raw/archive/manifest.jsonl")
DEFAULT_DB = Path("data/forum.sqlite")
DEFAULT_CSV = Path("data/coverage.csv")
DEFAULT_WIKI = Path("wiki")
DEFAULT_MIRROR_DIR = "Источники"
# Подкаталог зеркала FAQ ВНУТРИ --mirror-dir — ровно то же место, куда
# `mirror_faq.write_all` писал заметки до этой правки (`wiki/Источники/
# FAQ/`), просто теперь путь собирается в одном месте, а не подразумевается.
DEFAULT_FAQ_MIRROR_DIRNAME = "FAQ"
DEFAULT_ASSETS_MANIFEST = Path("data/assets/manifest.jsonl")
DEFAULT_ASSETS_ROOT = Path("data/assets/files")
DEFAULT_SITE_ROOT = Path("data/raw/site")
DEFAULT_SITE_MANIFEST = Path("data/raw/site/manifest-site.jsonl")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pipeline.run",
        description="Конвейер subaru-faq: сырой HTML архива -> SQLite -> зеркало Obsidian.")
    p.add_argument("command", choices=["ingest", "coverage", "mirror", "check", "all", "assets", "site", "faq"])
    p.add_argument("sub_action", nargs="?", choices=["index", "download", "build", "fetch", "load", "mirror"],
                   default=None,
                   help="для command=assets: index — индексация CDX, download — скачивание; "
                        "для command=site: build — план по CDX, fetch — скачивание по плану; "
                        "для command=faq: load — только разбор в SQLite, mirror (см. --mirror-dir) — "
                        "только генерация заметок, без действия — оба")
    p.add_argument("site_section", nargs="?", choices=["faq", "blogs"], default=None,
                   help="для command=site: какой раздел (build/fetch — оба обязаны его знать)")
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
    p.add_argument("--site-root", type=Path, default=DEFAULT_SITE_ROOT,
                   help="план (`plan-<раздел>.json`) и скачанные страницы FAQ/блогов "
                        "(по умолчанию %s)" % DEFAULT_SITE_ROOT)
    p.add_argument("--site-manifest", type=Path, default=DEFAULT_SITE_MANIFEST,
                   help="манифест добора сайта (по умолчанию %s)" % DEFAULT_SITE_MANIFEST)
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
        if args.sub_action not in ("index", "download"):
            print("укажи действие: assets index | assets download")
            return 2
        conn = db.connect(args.db)
        db.init_schema(conn)
        if args.sub_action == "index":
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

    if cmd == "faq":
        if args.sub_action not in (None, "load", "mirror"):
            print("укажи действие: faq load | faq mirror (без действия — оба)")
            return 2
        if args.rebuild:
            _drop_db(args.db)
            print("база пересоздана с нуля: %s" % args.db)
        conn = db.connect(args.db)
        db.init_schema(conn)
        faq_mirror_path = args.wiki / args.mirror_dir / DEFAULT_FAQ_MIRROR_DIRNAME
        if args.sub_action in (None, "load"):
            stats = parse_faq.load_all(args.site_root, args.site_manifest, conn)
            print("faq загрузка:", stats)
        if args.sub_action in (None, "mirror"):
            try:
                n = mirror_faq.write_all(conn, faq_mirror_path)
            except RuntimeError as e:
                print("ОШИБКА:", e)
                return 2
            print("faq заметок:", n, "->", faq_mirror_path)
        return 0

    if cmd == "site":
        if args.sub_action not in ("build", "fetch") or args.site_section is None:
            print("укажи действие и раздел: site build faq|blogs | site fetch faq|blogs")
            return 2
        if args.sub_action == "build":
            plan = fetch_site.build_list(args.site_section)
            path = fetch_site.save_plan(args.site_section, plan, root=args.site_root)
            print("план %s: %d адресов -> %s" % (args.site_section, len(plan), path))
        else:
            try:
                plan = fetch_site.load_plan(args.site_section, root=args.site_root)
            except FileNotFoundError:
                print("плана нет: %s (сначала site build %s)" % (args.site_root, args.site_section))
                return 2
            stats = fetch_site.fetch_all(plan, args.site_root, args.site_manifest, limit=args.limit)
            print("скачивание %s:" % args.site_section, stats)
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
        # FAQ — независимый от форума источник (свой манифест `--site-
        # manifest`, свои таблицы `faq`/`faq_images`), но его загрузчик
        # обязан жить внутри `ingest`/`all`, а не только в отдельной команде
        # `faq`: иначе `all --rebuild` пересоздаёт схему без данных FAQ, и
        # "снёс и собрал заново — получил ровно то же" перестаёт быть
        # верным для этого раздела (см. ревизию задачи 6). Отсутствие
        # `--site-manifest` на диске — не ошибка (`parse_faq.load_all`
        # молча даёт 0 записей), а не повод падать: чистый чекаут без
        # добора FAQ должен всё равно собираться.
        print("faq загрузка:", parse_faq.load_all(args.site_root, args.site_manifest, conn))

    if cmd in ("coverage", "all"):
        rows = coverage.report(conn)
        coverage.to_csv(rows, args.csv)
        print("покрытие:", coverage.summary(rows), "->", args.csv)

    if cmd in ("mirror", "all"):
        faq_mirror_path = mirror_path / DEFAULT_FAQ_MIRROR_DIRNAME
        try:
            print("заметок:", mirror.write_all(conn, mirror_path), "->", mirror_path)
            print("faq заметок:", mirror_faq.write_all(conn, faq_mirror_path), "->", faq_mirror_path)
        except RuntimeError as e:
            # Предохранитель генератора (общий у mirror и mirror_faq): база
            # не описывает это зеркало. Печатаем причину без трейсбека и
            # уходим с ненулевым кодом.
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
