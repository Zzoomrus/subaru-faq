"""Точка входа конвейера: `python -m pipeline.run <команда>`.

Пока прогон существовал только как heredoc в документе, документ и
реальность расходились при первой же правке кода. Следующая фаза — это
повторные прогоны (добор картинок, перегенерация зеркала, проверка), им
нужна команда, а не рецепт.

Команды:

    ingest        разобрать сырые страницы в SQLite (`--rebuild` — с нуля;
                  включает форум, FAQ и блоги — см. `faq`/`blog` ниже; после
                  загрузки восстанавливает состояние добора Ф2 из манифеста
                  `--assets-manifest`/`--assets-root` — см. задачу 8 ниже)
    coverage      отчёт покрытия в CSV + сводка в stdout
    mirror        сгенерировать зеркало `wiki/Источники` (форум + FAQ + блоги)
    check         проверка целостности всей вики (код возврата 1 при находках)
    all           всё перечисленное подряд
    faq [load|mirror]  FAQ отдельно от полного прогона: load — только разбор
                       сырых страниц раздела (`--site-root`/`--site-manifest`)
                       в таблицы `faq`/`faq_images`, mirror — только заметки
                       в `<--wiki>/<--mirror-dir>/FAQ/`, без действия — оба
                       (тот же код, что и внутри `ingest`/`mirror`/`all` —
                       для точечного повтора без полного форумного прогона)
    blog [load|mirror]  блоги (задача 7), тот же приём, что у `faq` — load в
                       таблицы `blog_posts`/`blog_images`/`blog_comments`,
                       mirror — заметки в `<--wiki>/<--mirror-dir>/Блоги/`
    dedup         дедуп FAQ между движками (Ф3, задача 1) — точечный повтор
                  без полного `ingest`; внутри `ingest`/`all` уже включён
    facts         Ф3, задача 4, проход 1: читает `<--articles-dir>/факты/
                  <--key>.json` (JSON-факты, выданные ИИ), прогоняет через
                  `pipeline.facts.check_all` (дословность цитаты по телу
                  заметки + автор/дата из `--db`), пишет `<--articles-dir>/
                  проверено/<--key>.json` — отброшенные факты остаются в
                  том же файле, не теряются
    article       Ф3, задача 5, проход 2: читает `<--root>/articles/
                  черновики/<--key>.md` (проза ИИ с маркерами `[^f1]` +
                  frontmatter заголовок/путь/узел/модель) и `<--root>/
                  articles/проверено/<--key>.json` (выход `facts`), пишет
                  готовую заметку в `<--root>/wiki/Статьи/<путь>/
                  <заголовок>.md` — сноску (ссылку и цитату) рендерит код
                  (`pipeline.articles.render`), не ИИ
    assets index    добор Ф2: индексация CDX (тела не тянет, ~40 мин на 6008 URL)
    assets sieve    просев уже скачанного: заглушки хостингов (1x1 пиксель и
                    прочее, что валидно как картинка, но картинкой поста быть
                    не может). Только диск, сети не трогает. Без `--apply` —
                    отчёт; с `--apply` — пометка `empty` в манифесте плюс
                    синхронизация с базой, после чего нужен `run mirror`
    assets download добор Ф2: скачивание тел там, где индексация нашла снимок
                    (`--retry no_snapshot,empty` — перезапросить терминальные
                    статусы, см. `fetch_assets.RETRIABLE_BY_FLAG`; по умолчанию
                    перезапрашивается только `failed`)
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

**Задача 8 (сведение концов фазы Ф2).** Само СКАЧИВАНИЕ (`assets index`/
`download`) остаётся вне `all` по причине выше — это не меняется. Но
ВОССТАНОВЛЕНИЕ уже скачанного состояния в `attachments.local_path` теперь
живёт и внутри `ingest`/`all` (сразу после загрузки форума/FAQ/блогов,
`assets_state.sync_to_db`), не только внутри `assets`: иначе `--rebuild`
(«снёс базу и собрал заново») стирал бы весь добор в NULL при каждой
пересборке — ровно тот сценарий, который проверяет главная гарантия фазы
(`data/` вне git, состояние обязано быть пере-выводимым из манифеста +
файлов на диске). `mirror`/`all` теперь также копируют реально
использованные файлы вложений форума в `<wiki>/<mirror-dir>/assets/` (тот
же приём, что уже был у `mirror_faq`/`mirror_blog`, см. `pipeline/mirror.py`)
— оба шага читают один и тот же `--assets-root`.

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
import json
import logging
import sys
from pathlib import Path

from pipeline import (archive_assets, articles, assets_state, attachments, check_mirror, coverage, db,
                      facts, faq_dedup, fetch_assets, fetch_site, ingest, mirror, mirror_blog,
                      mirror_faq, parse_blog, parse_faq)

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
# Подкаталог зеркала блогов ВНУТРИ --mirror-dir (задача 7, тот же приём,
# что у FAQ) — `wiki/Источники/Блоги/`.
DEFAULT_BLOG_MIRROR_DIRNAME = "Блоги"
DEFAULT_ASSETS_MANIFEST = Path("data/assets/manifest.jsonl")
DEFAULT_ASSETS_ROOT = Path("data/assets/files")
DEFAULT_SITE_ROOT = Path("data/raw/site")
DEFAULT_SITE_MANIFEST = Path("data/raw/site/manifest-site.jsonl")
# Корень черновиков/фактов статей Ф3 (задача 4): `<articles-dir>/факты/
# <ключ>.json` (вход, проход 1 — выдача ИИ) -> `<articles-dir>/проверено/
# <ключ>.json` (выход `facts.check_all`, задача 5 читает его как вход).
DEFAULT_ARTICLES_DIR = Path("articles")
# Корень проекта для команды `article` (задача 5): `pipeline.articles.build`
# фиксирует оба пути от ОДНОГО корня (`<root>/articles/…`, `<root>/wiki/
# Статьи/…`) — это его контракт (см. докстринг `articles.build`), поэтому
# команда не собирает их из `--articles-dir`/`--wiki` по отдельности (те
# двух разных корней не подразумевают вовсе — совпадение значений по
# умолчанию с `DEFAULT_ARTICLES_DIR`/`DEFAULT_WIKI` не повод молча считать
# их равными общему корню, если пользователь переопределит только один из
# двух флагов).
DEFAULT_ROOT = Path(".")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pipeline.run",
        description="Конвейер subaru-faq: сырой HTML архива -> SQLite -> зеркало Obsidian.")
    p.add_argument("command", choices=["ingest", "coverage", "mirror", "check", "all", "assets", "site",
                                        "faq", "blog", "dedup", "facts", "article"])
    p.add_argument("sub_action", nargs="?",
                   choices=["index", "download", "sieve", "build", "fetch", "load", "mirror"],
                   default=None,
                   help="для command=assets: index — индексация CDX, download — скачивание, "
                        "sieve — просев уже скачанного на заглушки хостингов (сеть не нужна); "
                        "для command=site: build — план по CDX, fetch — скачивание по плану; "
                        "для command=faq/blog: load — только разбор в SQLite, mirror (см. --mirror-dir) — "
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
    # Архив картинок Ф0/Ф1 — ДРУГОЙ манифест, чем `--assets-manifest` (тот про
    # добор Ф2). Из него берутся картинки FAQ и блогов: они никогда не
    # качались отдельно, но часть адресов — свой хост, и файл уже лежал в
    # архиве прошлой фазы. До этой правки путь был неявным (значения по
    # умолчанию внутри `mirror_faq`), а теперь один и тот же флаг кормит и
    # генератор зеркала, и отражение в базе (`archive_assets.sync_local_
    # paths`) — иначе они могли бы смотреть в разные каталоги.
    p.add_argument("--archive-assets-manifest", type=Path,
                   default=archive_assets.DEFAULT_MANIFEST,
                   help="манифест картинок архива Ф0/Ф1 (по умолчанию %s)"
                        % archive_assets.DEFAULT_MANIFEST)
    p.add_argument("--archive-assets-root", type=Path, default=archive_assets.DEFAULT_ROOT,
                   help="каталог файлов архива Ф0/Ф1 (по умолчанию %s)" % archive_assets.DEFAULT_ROOT)
    p.add_argument("--limit", type=int, default=None,
                   help="ограничить число URL за прогон (для проб/тестов)")
    # Терминальные статусы добора (`no_snapshot` 5007, `empty` 99) по
    # умолчанию не перезапрашиваются никогда — это 5106 обращений к архиву за
    # прогон впустую (Ruling 33 + уточнение лида). Флаг — «осознанная
    # операция»: посмотреть, не появилось ли в Wayback новых снимков спустя
    # время. `failed` в флаге не нужен: он перезапрашивается по умолчанию.
    p.add_argument("--apply", action="store_true",
                   help="для assets sieve: не только показать, но и пометить найденные "
                        "заглушки `empty` в манифесте (по умолчанию — только отчёт)")
    p.add_argument("--retry", default="",
                   help="перезапросить терминальные статусы добора: "
                        "no_snapshot (заново спросить CDX на шаге index), "
                        "empty (заново скачать на шаге download) или оба через "
                        "запятую. По умолчанию не перезапрашивается ни один: "
                        "это часы работы и тысячи запросов к архиву")
    p.add_argument("--key", default=None,
                   help="для command=facts: ключ статьи — читает "
                        "<--articles-dir>/факты/<ключ>.json, пишет "
                        "<--articles-dir>/проверено/<ключ>.json; "
                        "для command=article: читает <--root>/articles/черновики/<ключ>.md "
                        "и <--root>/articles/проверено/<ключ>.json")
    p.add_argument("--articles-dir", type=Path, default=DEFAULT_ARTICLES_DIR,
                   help="корень черновиков/фактов/проверенного статей Ф3 (по умолчанию %s)"
                        % DEFAULT_ARTICLES_DIR)
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                   help="для command=article: корень проекта — <root>/articles и <root>/wiki "
                        "(по умолчанию текущий каталог %s; см. DEFAULT_ROOT)" % DEFAULT_ROOT)
    return p


def mirror_assets_dir(mirror_path: Path) -> Path:
    """Путь ОБЩЕГО каталога вложений `<mirror_path>/assets` (задача 2 Ф3,
    Ruling 37) — единственное место, которое считает эту формулу.

    Находка ревью: до этой правки её считали инлайном в трёх местах
    (`build_mirror` и точечные команды `faq mirror`/`blog mirror` в
    `main()`) — три копии одной и той же строки, и откат передачи каталога
    в любой из точечных команд не ловился тестом на двух других, потому что
    сравнивать было не с чем: у каждого места была СВОЯ формула, просто
    совпадающая по значению. Теперь `build_mirror` и обе точечные команды
    зовут эту функцию, а не пишут `<путь> / "assets"` заново.
    """
    return Path(mirror_path) / "assets"


def build_mirror(conn, mirror_path: Path, assets_root: Path = DEFAULT_ASSETS_ROOT,
                  archive_assets_manifest: Path = archive_assets.DEFAULT_MANIFEST,
                  archive_assets_root: Path = archive_assets.DEFAULT_ROOT) -> dict[str, int]:
    """Собирает все три раздела зеркала (форум, FAQ, блоги) в дерево
    `mirror_path`, все три — в ОДИН общий каталог вложений `mirror_assets_
    dir(mirror_path)` (задача 2 Ф3, Ruling 37 Ф2: до этой правки FAQ и блоги
    копировали друг с другом и с форумом общие картинки каждый себе — 90
    картинок в два-три каталога, 108 лишних копий по оценке решения (90 по
    факту — см. отчёт задачи), 7,68 МиБ; следующая фаза добавит статьи,
    которые встраивают те же файлы, и без общего каталога один адрес получил
    бы третью копию).

    Точка сборки ВСЕХ ТРЁХ разделов разом — ОДНА, не три раздельных вызова:
    все три генератора получают один и тот же путь общего каталога. Её
    зовёт `main()` для команд `mirror`/`all`. Точечные `faq mirror`/`blog
    mirror` эту функцию НЕ зовут (они собирают только один раздел, а не все
    три) — но берут тот же путь через `mirror_assets_dir`, а не считают его
    заново (см. её докстринг).

    Возвращает число заметок по разделам (`forum`/`faq`/`blog`) — то же, что
    печатает `main()`.
    """
    mirror_path = Path(mirror_path)
    assets_dir = mirror_assets_dir(mirror_path)
    faq_path = mirror_path / DEFAULT_FAQ_MIRROR_DIRNAME
    blog_path = mirror_path / DEFAULT_BLOG_MIRROR_DIRNAME
    n_forum = mirror.write_all(conn, mirror_path, assets_root=assets_root, assets_dir=assets_dir)
    n_faq = mirror_faq.write_all(conn, faq_path, assets_manifest=archive_assets_manifest,
                                  assets_root=archive_assets_root, assets_dir=assets_dir)
    n_blog = mirror_blog.write_all(conn, blog_path, assets_manifest=archive_assets_manifest,
                                    assets_root=archive_assets_root, assets_dir=assets_dir)
    return {"forum": n_forum, "faq": n_faq, "blog": n_blog}


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
        if args.sub_action not in ("index", "download", "sieve"):
            print("укажи действие: assets index | assets download | assets sieve")
            return 2
        conn = db.connect(args.db)
        db.init_schema(conn)
        if args.sub_action == "sieve":
            # Просев (Ruling 45): по байтам на диске, без сети. Печатает и
            # ОДНОЗНАЧНЫЕ заглушки (сторона <= 2 px), и группы байт-идентичных
            # файлов у трёх и более адресов — вторые НЕ метятся сами никогда,
            # по ним решает человек, глядя на картинку.
            report = fetch_assets.sieve_report(conn, args.assets_manifest, args.assets_root)
            by_reason: dict[str, int] = {}
            for item in report["placeholders"]:
                by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
            print("заглушки: %d" % len(report["placeholders"]))
            for reason, count in sorted(by_reason.items(), key=lambda kv: -kv[1]):
                print("  по основанию «%s»: %d" % (reason, count))
            for item in report["placeholders"][:20]:
                print("  %s  %d байт %s — %s"
                      % (item["url"], item["bytes"], item["size"], item["reason"]))
            if len(report["placeholders"]) > 20:
                print("  … ещё %d" % (len(report["placeholders"]) - 20))
            print("НЕРЕШЁННЫЕ группы байт-идентичных файлов у >= 3 адресов: %d "
                  "(САМИ НЕ МЕТЯТСЯ никогда — открой образец глазами и, если это "
                  "заглушка, впиши её sha256 в attachments.DECIDED_PLACEHOLDER_SHA256)"
                  % len(report["identical_groups"]))
            for g in report["identical_groups"]:
                print("  %d байт, %s, адресов %d, образец %s"
                      % (g["bytes"], g["size"], g["urls"], g["sample"]))
            if not args.apply:
                print("это только отчёт; чтобы пометить заглушки `empty` в манифесте — "
                      "повтори с --apply, затем перегенерируй зеркало (`run mirror`)")
                return 0
            n = fetch_assets.mark_empty(args.assets_manifest,
                                        [i["url"] for i in report["placeholders"]])
            print("помечено `empty` в манифесте:", n)
            print("синхронизация с базой:",
                  assets_state.sync_to_db(conn, args.assets_manifest, args.assets_root))
            return 0
        retry = tuple(x.strip() for x in args.retry.split(",") if x.strip())
        try:
            if args.sub_action == "index":
                stats = fetch_assets.index_pending(conn, args.assets_manifest,
                                                    limit=args.limit, retry=retry)
                print("индексация:", stats)
            else:
                stats = fetch_assets.download(conn, args.assets_manifest, args.assets_root,
                                               limit=args.limit, retry=retry)
                print("скачивание:", stats)
        except ValueError as e:
            # Неизвестный статус в `--retry` — ошибка вызова, а не повод
            # молча ничего не перезапросить (иначе опечатка выглядит как
            # «нового в архиве не появилось»).
            print("ОШИБКА:", e)
            return 2
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
            print("картинки в базе:", archive_assets.sync_local_paths(
                conn, args.archive_assets_manifest, args.archive_assets_root))
        if args.sub_action in (None, "mirror"):
            # Общий каталог вложений (задача 2 Ф3, Ruling 37) — тот же путь,
            # что строит `build_mirror` для команды `all`, взятый ОДНОЙ
            # функцией (`mirror_assets_dir`), а не пересчитанный здесь же:
            # точечный `faq mirror` не должен заводить свой каталог
            # `FAQ/assets`, иначе перегенерация всей вики (`all`) с общим
            # каталогом снова разложит те же картинки по двум местам.
            try:
                n = mirror_faq.write_all(conn, faq_mirror_path,
                                          assets_manifest=args.archive_assets_manifest,
                                          assets_root=args.archive_assets_root,
                                          assets_dir=mirror_assets_dir(args.wiki / args.mirror_dir))
            except RuntimeError as e:
                print("ОШИБКА:", e)
                return 2
            print("faq заметок:", n, "->", faq_mirror_path)
        return 0

    if cmd == "blog":
        if args.sub_action not in (None, "load", "mirror"):
            print("укажи действие: blog load | blog mirror (без действия — оба)")
            return 2
        if args.rebuild:
            _drop_db(args.db)
            print("база пересоздана с нуля: %s" % args.db)
        conn = db.connect(args.db)
        db.init_schema(conn)
        blog_mirror_path = args.wiki / args.mirror_dir / DEFAULT_BLOG_MIRROR_DIRNAME
        if args.sub_action in (None, "load"):
            stats = parse_blog.load_all(args.site_root, args.site_manifest, conn)
            print("blog загрузка:", stats)
            print("картинки в базе:", archive_assets.sync_local_paths(
                conn, args.archive_assets_manifest, args.archive_assets_root))
        if args.sub_action in (None, "mirror"):
            # Общий каталог вложений через `mirror_assets_dir` — см. тот же
            # комментарий у `faq` выше.
            try:
                n = mirror_blog.write_all(conn, blog_mirror_path,
                                           assets_manifest=args.archive_assets_manifest,
                                           assets_root=args.archive_assets_root,
                                           assets_dir=mirror_assets_dir(args.wiki / args.mirror_dir))
            except RuntimeError as e:
                print("ОШИБКА:", e)
                return 2
            print("blog заметок:", n, "->", blog_mirror_path)
        return 0

    if cmd == "dedup":
        # FAQ (Ф3, задача 1): раздел архивирован двумя движками разом, и
        # часть записей повторяется. Отдельная команда — для точечного
        # повторного прогона дедупа без полного `ingest` (тот же приём,
        # что у `faq`/`blog` выше). Внутри `ingest`/`all` тот же вызов
        # живёт безусловно (см. ниже) — иначе `--rebuild` вернул бы базу
        # без указателей на дубли.
        conn = db.connect(args.db)
        db.init_schema(conn)
        print("дедуп faq:", faq_dedup.apply(conn))
        return 0

    if cmd == "facts":
        # Проход 1 фазы Ф3 (задача 4): читает JSON-факты, выданные ИИ по
        # одной теме/записи, и прогоняет их через механический гейт
        # дословности (`pipeline.facts.check_all`). Отброшенные факты
        # остаются В ТОМ ЖЕ выходном файле, а не отбрасываются молча — доля
        # брака входит в замеры фазы (бриф задачи 4, шаг 5).
        if not args.key:
            print("укажи ключ статьи: --key <ключ> "
                  "(читает <--articles-dir>/факты/<ключ>.json)")
            return 2
        facts_path = args.articles_dir / "факты" / (args.key + ".json")
        if not facts_path.exists():
            print("файл фактов не найден: %s" % facts_path)
            return 2
        # Автора/дату проверенный факт обязан нести ИЗ БАЗЫ (не из ответа
        # ИИ, см. docstring `facts._lookup_meta`) — без базы фактам просто
        # неоткуда их взять, поэтому отсутствующая база здесь такая же
        # ошибка вызова, как у `coverage`/`mirror` (см. комментарий ниже),
        # а не молчаливый пропуск атрибуции.
        if not args.db.exists():
            print("база не найдена: %s (нужна для автора/даты подтверждённых "
                  "фактов — python -m pipeline.run ingest)" % args.db)
            return 2
        conn = db.connect(args.db)
        db.init_schema(conn)
        raw = json.loads(facts_path.read_text(encoding="utf-8"))
        result = facts.check_all(raw, args.wiki / args.mirror_dir, conn)
        out_path = args.articles_dir / "проверено" / (args.key + ".json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("факты:", result["статистика"], "->", out_path)
        return 0

    if cmd == "article":
        # Проход 2 фазы Ф3 (задача 5): читает черновик прозы ИИ + проверенные
        # факты прохода 1 (`facts.check_all`) и пишет готовую заметку в
        # `wiki/Статьи`. Сноску (ссылку и цитату) рендерит `pipeline.articles`
        # из данных факта, а не парсит из черновика — см. докстринг модуля.
        if not args.key:
            print("укажи ключ статьи: --key <ключ> "
                  "(читает <--root>/articles/черновики/<ключ>.md "
                  "и <--root>/articles/проверено/<ключ>.json)")
            return 2
        try:
            out_path = articles.build(args.key, args.root)
        except (FileNotFoundError, articles.DraftError) as e:
            print("ОШИБКА:", e)
            return 2
        print("статья собрана:", out_path)
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
        # Дедуп FAQ (Ф3, задача 1): раздел архивирован двумя движками
        # разом (см. `pipeline/faq_dedup.py`) — сразу после загрузки, а не
        # только через отдельную команду `dedup`: иначе `--rebuild` («снёс
        # базу и собрал заново») вернул бы записи БЕЗ указателей на дубли,
        # и следующий прогон статей молча дал бы старой записи вторую
        # сноску (тот же класс ошибки, что чинили `sync_to_db`/`local_path`
        # в Ф2). `apply` идемпотентен — сбрасывает указатели перед
        # пересчётом, повторный вызов не копит мусор.
        print("дедуп faq:", faq_dedup.apply(conn))
        # Блоги (задача 7) — тот же приём, что и FAQ выше: живёт внутри
        # ingest/all, а не только в отдельной команде `blog`, иначе
        # `all --rebuild` пересоздаёт схему без данных блогов.
        print("blog загрузка:", parse_blog.load_all(args.site_root, args.site_manifest, conn))
        # Добор Ф2 (задача 8): состояние вложений (что скачалось и куда
        # легло) живёт в манифесте `--assets-manifest` + файлах на диске
        # (`pipeline/assets_state.py`), НЕ в базе — база пере-выводима из
        # сырого HTML одной командой, а манифест — единственная память про
        # добор. Без этого шага `ingest --rebuild`/`all --rebuild` стирали
        # бы `attachments.local_path` в NULL при каждой пересборке, и
        # "снёс — собрал — получил то же" было бы ложью именно для добора
        # (глобальное ограничение фазы «состояние добора обязано быть
        # пере-выводимым»). Отсутствующий манифест — не ошибка (`sync_to_db`
        # молча ничего не находит через `load()`), а не повод падать: чистый
        # чекаут без добора всё равно должен собираться.
        print("синхронизация добора:", assets_state.sync_to_db(conn, args.assets_manifest, args.assets_root))
        # То же самое для картинок FAQ и блогов, только источник другой —
        # архив Ф0/Ф1 (находка ре-ревью: `local_path` был NULL у ВСЕХ 669
        # строк, хотя в вики стояли 401 настоящая вставка; база отвечала
        # «ни одна картинка не уцелела» при 401 уцелевшей). Как и выше,
        # шаг обязан жить внутри `ingest`/`all`: загрузчики пересоздают
        # строки картинок, и без него `--rebuild` возвращал бы NULL.
        print("картинки в базе:", archive_assets.sync_local_paths(
            conn, args.archive_assets_manifest, args.archive_assets_root))

    if cmd in ("coverage", "all"):
        rows = coverage.report(conn)
        coverage.to_csv(rows, args.csv)
        print("покрытие:", coverage.summary(rows), "->", args.csv)

    if cmd in ("mirror", "all"):
        faq_mirror_path = mirror_path / DEFAULT_FAQ_MIRROR_DIRNAME
        blog_mirror_path = mirror_path / DEFAULT_BLOG_MIRROR_DIRNAME
        # Три генератора зовутся через одну точку сборки (`build_mirror`) —
        # она же считает путь ОБЩЕГО каталога вложений `<mirror_path>/assets`
        # (задача 2 Ф3, Ruling 37) и передаёт его во все три, а не три раза
        # подряд заново подразумевает то же самое.
        try:
            counts = build_mirror(conn, mirror_path, assets_root=args.assets_root,
                                   archive_assets_manifest=args.archive_assets_manifest,
                                   archive_assets_root=args.archive_assets_root)
        except RuntimeError as e:
            # Предохранитель генератора (общий у mirror и mirror_faq): база
            # не описывает это зеркало. Печатаем причину без трейсбека и
            # уходим с ненулевым кодом.
            print("ОШИБКА:", e)
            return 2
        print("заметок:", counts["forum"], "->", mirror_path)
        print("faq заметок:", counts["faq"], "->", faq_mirror_path)
        print("blog заметок:", counts["blog"], "->", blog_mirror_path)

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
