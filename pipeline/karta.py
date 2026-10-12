"""Генерация `wiki/Карта базы.md` — точки входа в вики: все статьи по узлам и моделям."""
from __future__ import annotations
import re, sys
from pathlib import Path

WIKI = Path(__file__).resolve().parent.parent / "wiki"


def _front(p: Path) -> dict[str, str]:
    t = p.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---", t, re.S)
    d: dict[str, str] = {}
    if m:
        for line in m.group(1).split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                d[k.strip()] = v.strip()
    return d


def build() -> str:
    root = WIKI / "Статьи"
    out = ["---", "type: карта", "---", "", "# Карта базы", "",
           "Вики по архиву форума subaru-faq.ru. Каждая статья собрана из проверенных фактов с дословными цитатами; "
           "сноски ведут в `Источники/` — зеркало тем форума.", ""]
    total = 0
    for node in sorted(p for p in root.iterdir() if p.is_dir()):
        files = sorted(p for p in node.rglob("*.md"))
        if not files:
            continue
        out.append(f"## {node.name} ({len(files)})")
        out.append("")
        for f in files:
            rel = f.relative_to(WIKI).with_suffix("")
            fr = _front(f)
            n = fr.get("источников", "")
            tail = f" — источников: {n}" if n else ""
            out.append(f"- [[{rel.as_posix()}|{f.stem}]]{tail}")
            total += 1
        out.append("")
    src = sorted((WIKI / "Источники").glob("Тема *.md"))
    out.insert(8, f"Статей: **{total}**, тем-источников: **{len(src)}**.")
    out.insert(9, "")
    return "\n".join(out) + "\n"


def main() -> None:
    text = build()
    (WIKI / "Карта базы.md").write_text(text, encoding="utf-8")
    print(f"карта: {WIKI / 'Карта базы.md'} ({len(text)} символов)")


if __name__ == "__main__":
    main()
