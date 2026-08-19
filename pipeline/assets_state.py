"""Состояние добора: манифест на диске — истина, база — его отражение.

База (`forum.sqlite`) пересобирается из сырого HTML одной командой, и это её
ценное свойство: снёс — пересобрал — получил ровно то же. Добор узнаёт то,
чего в сыром HTML нет (какие картинки удалось скачать и куда они легли), и
если бы это знание жило только в базе, любая пересборка его бы стёрла.
Поэтому истина — манифест (JSONL, дописывается построчно) плюс сами файлы на
диске, а `sync_to_db` лишь восстанавливает по ним отражение в `attachments`.
"""
import json
import warnings
from pathlib import Path


def record(manifest: Path, url: str, path: str | None, status: str, note: str = "") -> None:
    """Дописать одну запись в манифест (append-only — не переписывает файл).

    Если предыдущий прогон оборвался посреди записи строки (нет завершающего
    `\\n`), эта запись сперва закрывает тот обрывок собственным переводом
    строки — иначе новая запись молча склеилась бы с чужим обрывком в одну
    неразбираемую строку, и `load()` потерял бы уже ОБЕ записи вместо одной
    повреждённой.
    """
    m = Path(manifest)
    m.parent.mkdir(parents=True, exist_ok=True)
    needs_separator = False
    if m.exists() and m.stat().st_size > 0:
        with open(m, "rb") as f:
            f.seek(-1, 2)
            needs_separator = f.read(1) != b"\n"
    with open(m, "a", encoding="utf-8") as f:
        if needs_separator:
            f.write("\n")
        f.write(json.dumps({"url": url, "path": path, "status": status, "note": note},
                            ensure_ascii=False) + "\n")


def load(manifest: Path) -> dict[str, dict]:
    """Состояние по URL: последняя запись в манифесте для данного URL побеждает.

    Манифест дописывается построчно во время суточного прогона, который может
    оборваться в любой момент — в том числе посреди записи самой строки. Такая
    незавершённая ПОСЛЕДНЯЯ строка — это ожидаемый след обрыва, не ошибка:
    молча пропускаем её, не теряя всё, что было записано раньше. А вот
    нечитаемая строка НЕ на последнем месте — это уже повреждение файла
    (обрыв портит только то, что дописывается в момент обрыва), о ней стоит
    сказать вслух через `warnings.warn`, продолжая при этом обработку.
    """
    out: dict[str, dict] = {}
    p = Path(manifest)
    if not p.exists():
        return out
    lines = p.read_text(encoding="utf-8").splitlines()
    last_idx = len(lines) - 1
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            if i != last_idx:
                warnings.warn(
                    f"assets_state: повреждена строка манифеста {p} (№{i + 1} из "
                    f"{len(lines)}, не последняя) — пропущена; это похоже на "
                    "повреждение файла, а не на обычный обрыв записи",
                    RuntimeWarning, stacklevel=2)
            # последняя строка не читается — обычный след обрыва, молча пропускаем
            continue
        out[rec["url"]] = rec
    return out


def sync_to_db(conn, manifest: Path, assets_root: Path) -> dict[str, int]:
    """Проставить в attachments то, что подтверждается манифестом и диском.

    Трогает только URL, присутствующие в манифесте — attachments со статусами
    `skip`/`pending`, о которых манифест ничего не говорит, остаются нетронутыми.
    Один URL может встречаться в нескольких строках attachments (одна картинка
    вставлена в несколько постов) — UPDATE по url обновляет их все разом, а
    счётчики в `stats` считают URL из манифеста, а не задетые строки: так цифры
    сходятся с числом реально скачанных файлов, а не с числом вставок картинки.

    `unknown_url` — счётчик ИСКЛЮЧАЮЩИЙ: если по URL из манифеста не нашлось ни
    одной строки в attachments (UPDATE не задел ничего — синхронизировать было
    нечего), запись считается только в `unknown_url`, а не одновременно ещё и
    в статусный бакет (`ok`/`lost`/...) — иначе сумма счётчиков расходилась бы
    с числом записей манифеста. Если такие URL нашлись, о них сообщается через
    `warnings.warn` — накопление большого числа неизвестных адресов означает,
    что манифест и база разошлись, и это стоит заметить сразу, а не по
    расхождению итоговых цифр.
    """
    stats = {"ok": 0, "lost": 0, "no_snapshot": 0, "failed": 0, "unknown_url": 0}
    unknown_urls: list[str] = []
    for url, rec in load(manifest).items():
        status, path = rec["status"], rec.get("path")
        if status == "ok":
            if path and (Path(assets_root) / path).exists():
                resolved = "ok"
            else:
                resolved, path = "lost", None    # манифест обещает файл, а его нет
        else:
            resolved = status
        cur = conn.execute(
            "UPDATE attachments SET local_path = ?, status = ? WHERE url = ?", (path, resolved, url))
        if cur.rowcount == 0:
            stats["unknown_url"] += 1
            unknown_urls.append(url)
        else:
            stats[resolved] = stats.get(resolved, 0) + 1
    conn.commit()
    if unknown_urls:
        shown = unknown_urls[:20]
        more = f" … ещё {len(unknown_urls) - 20}" if len(unknown_urls) > 20 else ""
        warnings.warn(
            f"assets_state.sync_to_db: {len(unknown_urls)} URL из манифеста "
            f"не найдены в attachments (не синхронизировано): {shown}{more}",
            RuntimeWarning, stacklevel=2)
    return stats
