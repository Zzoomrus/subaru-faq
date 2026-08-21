"""Генератор зеркала FAQ: заметка на каждую запись `faq` (Ф2, задача 6).

Формат заметки следует решениям задачи 7/8 (`pipeline.mirror`) там, где они
применимы, и переиспользует их код напрямую, а не копирует:

- тело ответа — та же позиционная подстановка картинок и та же пометка об
  утрате, что и в зеркале форума (`mirror.render_post_body`): картинки
  ложатся на своё место в тексте, файла нет -> однострочная пометка,
  экранирование `[[`/заголовков внутри ответа — то же самое (сноска на
  секцию `#Ответ` иначе оборвалась бы молча на первом же случайном "#"
  в тексте ответа, тот же класс риска, что и `#Пост <MID>` у форума);
- YAML-экранирование фронтматтера — `mirror._yaml_dquote`.

Заголовки внутри заметки: `# <вопрос>` (H1 — как у форума и блогов, M6
итогового ревью Ф2) и два адреса для сносок статей — `## Вопрос` и
`## Ответ` (`[[FAQ 502#Ответ]]`). Полный список обещанных адресов всех
трёх разделов проверяется тестом `tests/test_anchor_contract.py` и описан
для человека в `docs/контракт-зеркала.md`.

Имя заметки — НЕ просто "FAQ <номер>.md": разведка задачи 6 нашла, что
номер старого движка (`nr`) и номер Bitrix (`ELEMENT_ID`) — независимые
пространства, которые на живом корпусе реально пересекаются (17 из 177
файлов несут одно и то же число под РАЗНЫМ содержанием — подтверждено
сверкой текста вопроса, см. task-6-report.md). Поэтому:

- Bitrix (154 из 177, актуальный движок сайта) -> `FAQ <ELEMENT_ID>.md` —
  именно так, как попросил бриф, и то, что должны угадывать сноски статей;
- старый движок (23 из 177) -> `FAQ старый <nr>.md` — ВСЕГДА, а не только
  при обнаруженной коллизии: имя заметки обязано быть функцией ОДНОЙ
  записи, а не всего корпуса. Схема "суффикс только при коллизии" меняла
  бы имя уже существующей заметки при доборе новых страниц в будущем — тот
  же класс ошибки, от которого форумное зеркало защищается, отказываясь
  переименовывать заметки по названию темы (см. docstring `pipeline.mirror`).

Картинки: файлы раздела FAQ никогда не качались отдельно (сеть в задаче 6
не трогали вовсе), но часть URL (`upload/blog/...`) совпадает с уже
скачанными вложениями форума Ф0/Ф1 (`data/raw/archive/manifest-assets.jsonl`
+ `data/raw/archive/assets/`) — те же файлы на том же хосте, добытые раньше
по другому поводу. `write_all` ищет там, копирует найденное в
`<out_dir>/assets/<hash><ext>` (стабильное имя от URL, как в `fetch_assets.
local_name`) и подставляет относительный путь; остальное — честная пометка
об утрате (глобальное ограничение "ни одной битой картинки").

Путь вставки — относительно `out_dir` (`assets/<hash><ext>`), не от корня
вики: `write_all` не знает и не обязан знать, где именно относительно
корня вики его позовут. Резолвится это тем же способом, каким Obsidian и
`check_mirror.check` резолвят вставку при неоднозначном пути — по имени
файла (хэш делает его уникальным в пределах вики), см. `check_mirror.
_file_exists`. Если однажды окажется, что реальный vault сконфигурирован на
строго абсолютные ссылки (не "кратчайший путь") — это разойдётся с
Obsidian визуально, но `check_mirror` всё равно не даст ложной "битой
вставки" (см. отчёт задачи 6, раздел "сомнения").
"""
import re
from pathlib import Path

from pipeline import archive_assets, attachments, mirror

# Индекс и поиск файла в архиве Ф0/Ф1 переехали в `pipeline.archive_assets`
# (у логики стало два потребителя: зеркало и отражение в базе — `sync_local_
# paths`, и оба обязаны ходить одним кодом, иначе ответ базы «уцелела ли
# картинка» и содержимое вики разойдутся). Здесь — псевдонимы: на эти имена
# ссылается докстринг модуля, `mirror_blog` и тесты.
DEFAULT_ASSETS_MANIFEST = archive_assets.DEFAULT_MANIFEST
DEFAULT_ASSETS_ROOT = archive_assets.DEFAULT_ROOT

_NOTE_NAME = re.compile(r"^FAQ (?:старый )?(\d+)\.md$")

#: Текст генератора, а не автора — единственное определение (задача 3 Ф3,
#: ревью: `pipeline.notes.GENERATOR_PATTERNS` собирается ИЗ этих констант,
#: а не дублирует их буквально).
QUESTION_LOST = "(вопрос не сохранился)"
ANSWER_LOST = "(ответ не сохранился)"

_normalize_asset_path = archive_assets.normalize_path
_load_asset_index = archive_assets.load_index
_local_asset_name = attachments.asset_name


def _filename(engine: str, nr: int) -> str:
    return "FAQ %d.md" % nr if engine == "bitrix" else "FAQ старый %d.md" % nr


def _resolve_image(url: str, asset_index: set[str], assets_root: Path, dest_dir: Path) -> str | None:
    """Копирует картинку в зеркало, если файл уже есть в архиве Ф0/Ф1, и
    возвращает путь вставки (`assets/<hash><ext>`, см. docstring модуля).
    `None` — файла нет ни в манифесте, ни на диске: честная утрата.

    Поиск — `archive_assets.find`, то есть ровно та же функция, которой
    `archive_assets.sync_local_paths` заполняет `local_path` в базе.
    """
    rel = archive_assets.find(url, asset_index, assets_root)
    if rel is None:
        return None
    return mirror.copy_asset(url, Path(assets_root) / rel, dest_dir)


def render_entry(row: tuple, images_by_url: dict) -> str:
    (engine, nr, catnr, prog, category, question, answer_md, source_url, snapshot_ts, title,
     duplicate_of_engine, duplicate_of_nr) = row
    question = question or ""
    body = mirror.render_post_body(answer_md or "", images_by_url)

    # Тот же риск, что у ответа: вопрос идёт как обычный текст МЕЖДУ двумя
    # заголовками секций, случайный "[[" или ведущий "#" в исходном тексте
    # сломал бы структуру заметки так же молча, как и в теле ответа.
    question_line = mirror._escape_headings(mirror._escape_wikilink_open(question))

    # `title` (задача 6, ревизия по дефекту) — заголовок темы Bitrix, когда
    # он расходится с настоящим вопросом (см. `parse_faq._split_embedded_
    # qa`): показываем в "## Вопрос" вопрос, а название темы не теряем,
    # кладём вторым алиасом — по нему тоже находят заметку поиском/линком.
    aliases = [question]
    if title and title != question:
        aliases.append(title)
    aliases_line = ", ".join(mirror._yaml_dquote(a) for a in aliases)

    # Ф3, задача 1: запись — дубль другой, найденной `faq_dedup` (вопрос
    # совпал или ответ дословно вошёл в канонический). Пометка ставится и во
    # фронтматтере (`дубль_чего`, машиночитаемо — по нему легко отфильтровать
    # дубли скриптом), и коллаутом под H1 (человеку, читающему заметку
    # глазами, иначе ничего не заметно). Без этого исполнитель следующей
    # задачи Ф3, сославшись на старую запись, дал бы мысли вторую сноску.
    canonical_name = None
    if duplicate_of_engine is not None and duplicate_of_nr is not None:
        canonical_name = _filename(duplicate_of_engine, duplicate_of_nr)[:-len(".md")]

    out = ["---",
           "номер: %d" % nr,
           "движок: %s" % ("bitrix" if engine == "bitrix" else "старый"),
           "prog: %s" % mirror._yaml_dquote(prog or ""),
           "категория: %s" % mirror._yaml_dquote(category or ""),
           "адрес: %s" % mirror._yaml_dquote(source_url or ""),
           "снимок: %s" % mirror._yaml_dquote(snapshot_ts or ""),
           "aliases: [%s]" % aliases_line]
    if canonical_name is not None:
        out.append("дубль_чего: \"[[%s]]\"" % canonical_name)
    out += ["---", "",
           # H1 — то же, что у форума («# <название темы>») и блогов
           # («# <название записи>»): единственное расхождение структуры
           # трёх генераторов без обоснования (M6 итогового ревью Ф2).
           # Название заметки FAQ — это номер, поэтому в открытой заметке
           # и в графе связей человеку было не видно, о чём она.
           # `## Вопрос`/`## Ответ` остаются на месте: это АДРЕСА для
           # сносок Ф3 (`[[FAQ 502#Ответ]]`), H1 их не заменяет.
           "# %s" % (question_line or "FAQ %d" % nr), ""]
    if canonical_name is not None:
        out += ["> [!warning] Дубль",
                "> Эта запись — тот же материал, что [[%s]], сохранённый вторым движком сайта." % canonical_name,
                "> Ссылаться в статьях следует на каноническую запись: два указателя на одну мысль",
                "> читаются как два независимых свидетельства.", ""]
    out += ["## Вопрос", "",
           question_line or QUESTION_LOST, "",
           "## Ответ", ""]
    out.append(body if body else ANSWER_LOST)
    out.append("")
    return "\n".join(out)


def write_all(conn, out_dir: Path, assets_manifest: Path = DEFAULT_ASSETS_MANIFEST,
              assets_root: Path = DEFAULT_ASSETS_ROOT) -> int:
    """Пишет заметку на каждую запись `faq` и убирает заметки исчезнувших.

    Тот же предохранитель, что у `mirror.write_all`: удалений не может быть
    больше, чем записанных заметок — иначе пустая/чужая база молча снесла бы
    весь каталог с кодом возврата 0.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = out_dir / "assets"
    asset_index = _load_asset_index(assets_manifest)

    names: set[str] = set()
    used_assets: set[str] = set()
    n = 0
    rows = conn.execute(
        "SELECT engine, nr, catnr, prog, category, question, answer_md, source_url, snapshot_ts, title, "
        "duplicate_of_engine, duplicate_of_nr "
        "FROM faq ORDER BY engine, nr").fetchall()
    for row in rows:
        engine, nr = row[0], row[1]
        images_by_url = {}
        for (url,) in conn.execute(
                "SELECT url FROM faq_images WHERE engine = ? AND nr = ?", (engine, nr)):
            local = _resolve_image(url, asset_index, assets_root, assets_dir)
            if local:
                used_assets.add(local.rsplit("/", 1)[-1])
            images_by_url[url] = {"local_path": local}
        name = _filename(engine, nr)
        (out_dir / name).write_text(render_entry(row, images_by_url), encoding="utf-8")
        names.add(name)
        n += 1

    stale = [p for p in sorted(out_dir.glob("FAQ *.md")) if _NOTE_NAME.match(p.name) and p.name not in names]
    if len(stale) > n:
        raise RuntimeError(
            "отказ убирать заметки FAQ: записано %d, под удаление попало %d. "
            "Похоже, база не описывает это зеркало. Зеркало не тронуто: %s"
            % (n, len(stale), out_dir))
    for path in stale:
        path.unlink()
    mirror.prune_assets(assets_dir, used_assets, n)
    return n
