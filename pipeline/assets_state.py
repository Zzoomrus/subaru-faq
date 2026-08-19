"""Состояние добора: манифест на диске — истина, база — его отражение.

База (`forum.sqlite`) пересобирается из сырого HTML одной командой, и это её
ценное свойство: снёс — пересобрал — получил ровно то же. Добор узнаёт то,
чего в сыром HTML нет (какие картинки удалось скачать и куда они легли), и
если бы это знание жило только в базе, любая пересборка его бы стёрла.
Поэтому истина — манифест (JSONL, дописывается построчно) плюс сами файлы на
диске, а `sync_to_db` лишь восстанавливает по ним отражение в `attachments`.
"""
import json
from pathlib import Path


def record(manifest: Path, url: str, path: str | None, status: str, note: str = "") -> None:
    """Дописать одну запись в манифест (append-only — не переписывает файл)."""
    Path(manifest).parent.mkdir(parents=True, exist_ok=True)
    with open(manifest, "a", encoding="utf-8") as f:
        f.write(json.dumps({"url": url, "path": path, "status": status, "note": note},
                            ensure_ascii=False) + "\n")


def load(manifest: Path) -> dict[str, dict]:
    """Состояние по URL: последняя запись в манифесте для данного URL побеждает."""
    out: dict[str, dict] = {}
    p = Path(manifest)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rec = json.loads(line)
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
    """
    stats = {"ok": 0, "lost": 0, "no_snapshot": 0, "failed": 0, "unknown_url": 0}
    for url, rec in load(manifest).items():
        status, path = rec["status"], rec.get("path")
        if status == "ok":
            if path and (Path(assets_root) / path).exists():
                stats["ok"] += 1
            else:
                status, path = "lost", None      # манифест обещает файл, а его нет
                stats["lost"] += 1
        else:
            stats[status] = stats.get(status, 0) + 1
        cur = conn.execute(
            "UPDATE attachments SET local_path = ?, status = ? WHERE url = ?", (path, status, url))
        if cur.rowcount == 0:
            stats["unknown_url"] += 1
    conn.commit()
    return stats
