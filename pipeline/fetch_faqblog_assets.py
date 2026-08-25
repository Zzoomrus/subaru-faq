"""Добор картинок FAQ и блогов из Wayback — по образцу `fetch_assets` (Ф4).

Картинки этих двух разделов никогда не качались отдельно: сеть в задачах
6/7 Ф2 не трогали вовсе (см. `archive_assets.py`). Часть адресов — свой хост
сайта, и такие файлы уже нашлись в архиве прошлой фазы (`data/raw/archive/`);
на живой базе 2026-08-25 так закрылось 401 из 669 картинок. Остаток —
**268 строк / 262 уникальных URL** с `local_path IS NULL`, и для них
механизма не было вовсе. Этот модуль — он, собранный из тех же кирпичей,
что и добор форума, а не написанный с нуля:

- CDX-поиск, скачивание тела, пейсер, признак содержимого — из
  `pipeline.fetcher` и `pipeline.fetch_assets` (`_is_real_image`,
  `local_name`, `_try_candidates`, статусы `TERMINAL_STATUSES`/
  `RETRY_ON_DOWNLOAD`/`RETRIABLE_BY_FLAG`, валидатор `--retry`) — переиспользуются
  напрямую, не копируются: одна и та же логика "что значит пустышка", "что
  перезапрашивать" не должна разойтись между двумя доборами;
- манифест — тот же формат и код (`assets_state.record`/`load`), но СВОЙ
  файл (`DEFAULT_MANIFEST`, отдельно от манифеста форума): пул адресов другой
  (`faq_images`/`blog_images`, а не `attachments`), и путать историю одного
  добора с другим было бы неверно, даже если формат совпадает;
- каталог с файлами — ТОТ ЖЕ (`data/assets/files/`, `fetch_assets.
  DEFAULT_ROOT`/`mirror.DEFAULT_ASSETS_ROOT`): имя файла — хэш канонического
  адреса (`attachments.asset_name`), поэтому общий каталог не даёт коллизий
  и держит принцип Ф3 "один файл — одно имя, один каталог" (задача 2 Ф3);
- просев заглушек хостингов (Ruling 45) — `fetch_assets.sieve_report`/
  `mark_empty` дословно те же функции: они не завязаны на таблицу
  `attachments`, только на манифест и диск, поэтому звать их с ЭТИМ
  манифестом уже достаточно, отдельной копии не нужно.

## Пул адресов: не весь `faq_images ∪ blog_images`, а только то, чего нет в архиве

Наивный пул (все URL из обеих таблиц) спросил бы Wayback и про 401 адрес,
уже найденный в архиве Ф0/Ф1 — бессмысленная нагрузка на архив ровно за то,
за что банят. Проверка "уже есть в архиве" — `archive_assets.find` (тот же
код, которым `archive_assets.sync_local_paths` заполняет `local_path`), а не
чтение колонки `local_path` из базы: колонка пересоздаётся при каждой
загрузке (`archive_assets.sync_local_paths` зовётся безусловно и обнуляет
её для всего, чего нет в архиве) и не может служить устойчивым фильтром —
устойчив только сам архивный индекс на диске.

## `sync_to_db` не пересекается с `archive_assets.sync_local_paths`

Порядок вызова: сперва архив (как и раньше), потом этот модуль. Конфликта
нет по построению — пулы источников URL не пересекаются (архив покрывает
свой хост, этот манифест видит только то, чего в архиве не нашлось), и
`sync_to_db` трогает только строки, ещё имеющие `local_path IS NULL` после
архивного шага. Порядок всё равно обязателен для пересборки: `--rebuild`
пересоздаёт строки `faq_images`/`blog_images` заново (`local_path` = NULL у
всех), и без этого шага результат добора Wayback стирался бы на каждом
`ingest --rebuild`/`all --rebuild`, тем же классом бага, что уже чинили для
форума (`assets_state.sync_to_db`) и для архива (`archive_assets.
sync_local_paths`).
"""
import logging
from pathlib import Path

from pipeline import archive_assets, assets_state, fetch_assets, fetcher, mirror

_LOG = logging.getLogger(__name__)
_PROGRESS_EVERY = 50

#: Отдельный манифест от добора форума (`data/assets/manifest.jsonl`) —
#: другой пул URL, своя история.
DEFAULT_MANIFEST = Path("data/assets/manifest-faqblog.jsonl")

#: Тот же каталог, что и у форумных картинок (Ruling Ф3 задача 2: один файл
#: — одно имя от `attachments.asset_name`, один каталог на все разделы).
DEFAULT_ROOT = mirror.DEFAULT_ASSETS_ROOT

# Все картинки этих двух таблиц — именно картинки (в отличие от `local`-
# вложений форума, где тип неизвестен по адресу и мог быть документом):
# признак содержимого один на весь модуль, без ветвления по kind.
_is_real_image = fetch_assets._is_real_image


def _target_urls(conn, archive_index: set[str], archive_root: Path) -> list[str]:
    """Уникальные URL `faq_images`/`blog_images`, которых нет в архиве Ф0/Ф1.

    Не фильтрует по `local_path` в базе (значение пересоздаётся при каждой
    загрузке) — устойчивый фильтр только архивный индекс на диске, см.
    докстринг модуля.
    """
    urls: set[str] = set()
    for table in ("faq_images", "blog_images"):
        for (url,) in conn.execute(
                "SELECT DISTINCT url FROM %s WHERE url IS NOT NULL AND url <> ''" % table):
            urls.add(url)
    return sorted(u for u in urls if archive_assets.find(u, archive_index, archive_root) is None)


def _targets(conn, manifest: Path, want: str, limit: int | None, retry=(),
             archive_manifest: Path = archive_assets.DEFAULT_MANIFEST,
             archive_root: Path = archive_assets.DEFAULT_ROOT) -> list[str]:
    """Та же логика, что `fetch_assets._targets` (устройство и обоснование
    там же), только пул адресов из `_target_urls` вместо `attachments`."""
    retry_index, retry_download = fetch_assets._retry_targets(retry, want)
    known = assets_state.load(manifest)
    archive_index = archive_assets.load_index(archive_manifest)
    urls = _target_urls(conn, archive_index, archive_root)
    out = []
    for url in urls:
        state = known.get(url, {}).get("status")
        if want == "index" and (state is None or state in retry_index):
            out.append(url)
        elif want == "download" and (state in fetch_assets.RETRY_ON_DOWNLOAD or state in retry_download):
            out.append(url)
    return out[:limit] if limit else out


def index_pending(conn, manifest: Path, limit: int | None = None, retry=(),
                   archive_manifest: Path = archive_assets.DEFAULT_MANIFEST,
                   archive_root: Path = archive_assets.DEFAULT_ROOT) -> dict[str, int]:
    """Шаг 1: у скольких URL в CDX вообще есть снимок. См. `fetch_assets.
    index_pending` — устройство и вежливость (`pacer.note(True)` всегда,
    независимо от исхода) те же, обоснование там же."""
    stats = {"pending": 0, "no_snapshot": 0}
    pacer = fetcher.TokenBucketPacer()
    targets = _targets(conn, manifest, "index", limit, retry, archive_manifest, archive_root)
    total = len(targets)
    for i, url in enumerate(targets, 1):
        found = fetcher.cdx_find_snapshot(url)
        if found:
            ts, _original = found
            assets_state.record(manifest, url, None, "pending", note=ts)
            stats["pending"] += 1
        else:
            assets_state.record(manifest, url, None, "no_snapshot")
            stats["no_snapshot"] += 1
        pacer.note(True)
        if i % _PROGRESS_EVERY == 0 or i == total:
            _LOG.info("faq/blog индексация: %d/%d — pending=%d no_snapshot=%d",
                       i, total, stats["pending"], stats["no_snapshot"])
        pacer.wait()
    return stats


def download(conn, manifest: Path, assets_root: Path, limit: int | None = None, retry=(),
             archive_manifest: Path = archive_assets.DEFAULT_MANIFEST,
             archive_root: Path = archive_assets.DEFAULT_ROOT) -> dict[str, int]:
    """Шаг 2: качает тело только тем URL, у которых индексация нашла снимок.
    См. `fetch_assets.download` — устройство (один CDX-запрос за URL за весь
    шаг, а не за прогон) и обоснование те же."""
    stats = {"ok": 0, "empty": 0, "failed": 0}
    pacer = fetcher.TokenBucketPacer()
    known = assets_state.load(manifest)
    targets = _targets(conn, manifest, "download", limit, retry, archive_manifest, archive_root)
    total = len(targets)
    for i, url in enumerate(targets, 1):
        saved_ts = known.get(url, {}).get("note") or None
        saw_content = False

        data = None
        if saved_ts:
            data, seen = fetch_assets._try_candidates([(saved_ts, url)], _is_real_image)
            saw_content = saw_content or seen
        if data is None:
            data, seen = fetch_assets._try_candidates(fetcher.cdx_snapshots(url), _is_real_image)
            saw_content = saw_content or seen
        if data is None:
            reason = "empty" if saw_content else "failed"
            assets_state.record(manifest, url, None, reason)
            stats[reason] += 1
            pacer.note(reason != "failed")
        else:
            rel = fetch_assets.local_name(url, data)
            dst = Path(assets_root) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            assets_state.record(manifest, url, rel, "ok")
            stats["ok"] += 1
            pacer.note(True)
        if i % _PROGRESS_EVERY == 0 or i == total:
            _LOG.info("faq/blog скачивание: %d/%d — ok=%d empty=%d failed=%d",
                       i, total, stats["ok"], stats["empty"], stats["failed"])
        pacer.wait()
    return stats


def sync_to_db(conn, manifest: Path, assets_root: Path) -> dict[str, int]:
    """Проставить `faq_images.local_path`/`blog_images.local_path` из этого
    манифеста — только там, где `archive_assets.sync_local_paths` уже
    отработал и оставил `NULL` (см. докстринг модуля про порядок вызова и
    отсутствие пересечения пулов). Идемпотентно, как и `archive_assets.
    sync_local_paths`/`assets_state.sync_to_db`: значение выводится заново из
    манифеста и диска при каждом вызове, а не из предыдущего состояния базы.
    """
    known = assets_state.load(manifest)
    stats = {"faq_ok": 0, "faq_lost": 0, "blog_ok": 0, "blog_lost": 0}
    for table, prefix in (("faq_images", "faq"), ("blog_images", "blog")):
        rows = conn.execute(
            "SELECT id, url FROM %s WHERE local_path IS NULL" % table).fetchall()
        for row_id, url in rows:
            rec = known.get(url or "")
            rel = None
            if rec and rec.get("status") == "ok" and rec.get("path"):
                candidate = Path(assets_root) / rec["path"]
                if candidate.exists():
                    rel = rec["path"]
            conn.execute("UPDATE %s SET local_path = ? WHERE id = ?" % table, (rel, row_id))
            stats["%s_%s" % (prefix, "ok" if rel else "lost")] += 1
    conn.commit()
    return stats
