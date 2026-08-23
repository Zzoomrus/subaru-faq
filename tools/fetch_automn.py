#!/usr/bin/env python3
"""Забор руководства automn.ru (Subaru Legacy/Outback и Forester) в локальный архив.

Зачем. Ссылки на этот сайт лежат в архиве мёртвого форума; из восемнадцати
проверенных внешних ресурсов выжили два, и этот — единственный с полным
руководством по ремонту. Контент заморожен с 2008 года, сайт технически жив, но
гарантий нет: забираем копию, пока она есть.

Устройство. Обход в ширину от двух корней, только пути `/subaru-legacy-outback/`
и `/subaru-forester/` плюс картинки с любого пути (схемы лежат в общем
каталоге). Пауза между запросами обязательна: мы берём копию для личного
архива, а не устраиваем нагрузку.

Возобновляемость — главное требование, а не удобство. За три фазы этого проекта
прогоны рвались одиннадцать раз (сон машины, обрыв связи), и переживал их только
append-only манифест:每 успешная страница дописывается строкой сразу, повторный
запуск пропускает уже скачанное. Манифест не переписывается никогда.

Проверка содержимого, а не кода ответа. Урок Ф0: HTTP 200 не значит контент —
страница «DB query error» тоже двухсотка. Поэтому у HTML проверяется маркер
структуры, у картинок — сигнатура файла.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOTS = (
    "http://automn.ru/subaru-legacy-outback/",
    "http://automn.ru/subaru-forester/",
)
#: Пути, которые считаем своими. Общий каталог марок automn.ru не нужен.
ALLOWED_PREFIXES = ("/subaru-legacy-outback/", "/subaru-forester/")
#: Картинки берём с любого пути: схемы лежат в общем каталоге сайта.
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif")

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) personal-archive-copy"
DELAY_SECONDS = 2.5
TIMEOUT = 30
MAX_ATTEMPTS = 3

#: Маркер живой страницы руководства. Пустой шаблон и заглушка хостера его не
#: содержат, поэтому «200 без маркера» считается неудачей, а не успехом.
HTML_MARKER = re.compile(r"<title>.{3,}</title>", re.S | re.I)
IMAGE_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a")

LINK = re.compile(r'href=["\']([^"\'#]+)', re.I)
IMG = re.compile(r'src=["\']([^"\']+)', re.I)


def local_name(url: str) -> str:
    """Имя файла от полного адреса.

    Ключ — весь адрес, а не путь: урок Ф2 (решение 39). Там 50 разных вложений
    делили один путь и различались только строкой запроса; хэш пути дал бы им
    одно имя и подменил бы содержимое молча.
    """
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        suffix = ".html"
    return digest + suffix


def is_ours(url: str) -> bool:
    parts = urllib.parse.urlparse(url)
    if parts.netloc not in ("automn.ru", "www.automn.ru"):
        return False
    if Path(parts.path).suffix.lower() in IMAGE_SUFFIXES:
        return True
    return any(parts.path.startswith(p) for p in ALLOWED_PREFIXES)


def looks_real(data: bytes, url: str) -> bool:
    if Path(urllib.parse.urlparse(url).path).suffix.lower() in IMAGE_SUFFIXES:
        return any(data.startswith(sig) for sig in IMAGE_SIGNATURES)
    if len(data) < 500:
        return False
    text = data.decode("cp1251", errors="replace")
    return bool(HTML_MARKER.search(text))


def load_done(manifest: Path) -> dict[str, str]:
    done: dict[str, str] = {}
    if not manifest.exists():
        return done
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        done[row["url"]] = row["status"]
    return done


def fetch(url: str) -> bytes | None:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read()
        except (urllib.error.URLError, OSError) as exc:
            if attempt == MAX_ATTEMPTS:
                print(f"  отказ после {MAX_ATTEMPTS} попыток: {exc}", file=sys.stderr)
                return None
            time.sleep(DELAY_SECONDS * attempt)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/automn", help="куда складывать файлы")
    parser.add_argument("--delay", type=float, default=DELAY_SECONDS)
    parser.add_argument("--limit", type=int, default=0, help="0 — без ограничения")
    args = parser.parse_args()

    out = Path(args.out)
    (out / "files").mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.jsonl"

    done = load_done(manifest)
    seen: set[str] = set(done)
    queue: list[str] = [u for u in ROOTS if u not in done]
    seen.update(queue)

    # Возобновление: очередь восстанавливается из УЖЕ СКАЧАННЫХ страниц, а не
    # только из корней. Иначе повторный запуск видит корни в манифесте, находит
    # пустую очередь и молча заканчивает работу, не докачав ничего, — ровно это
    # и случилось на первом же перезапуске.
    for url, status in done.items():
        if status != "ok":
            continue
        path = out / "files" / local_name(url)
        if not path.suffix == ".html" or not path.exists():
            continue
        text = path.read_bytes().decode("cp1251", errors="replace")
        for raw in LINK.findall(text) + IMG.findall(text):
            nxt = urllib.parse.urljoin(url, raw.strip())
            nxt, _ = urllib.parse.urldefrag(nxt)
            if nxt not in seen and is_ours(nxt):
                seen.add(nxt)
                queue.append(nxt)

    fetched = failed = 0
    print(f"уже в манифесте: {len(done)}, в очереди: {len(queue)}")

    while queue:
        if args.limit and fetched >= args.limit:
            print(f"достигнут предел {args.limit}, очередь: {len(queue)}")
            break
        url = queue.pop(0)
        data = fetch(url)
        status = "ok"
        if data is None:
            status = "failed"
        elif not looks_real(data, url):
            status = "empty"

        if status == "ok":
            name = local_name(url)
            (out / "files" / name).write_bytes(data)
            fetched += 1
            # Ссылки собираем только со своих HTML-страниц.
            if name.endswith(".html"):
                text = data.decode("cp1251", errors="replace")
                for raw in LINK.findall(text) + IMG.findall(text):
                    nxt = urllib.parse.urljoin(url, raw.strip())
                    nxt, _ = urllib.parse.urldefrag(nxt)
                    if nxt not in seen and is_ours(nxt):
                        seen.add(nxt)
                        queue.append(nxt)
        else:
            failed += 1
            name = ""

        with manifest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"url": url, "status": status, "file": name},
                                ensure_ascii=False) + "\n")

        if (fetched + failed) % 25 == 0:
            print(f"  взято {fetched}, отказов {failed}, в очереди {len(queue)}", flush=True)
        time.sleep(args.delay)

    print(f"готово: взято {fetched}, отказов {failed}, всего в манифесте {len(load_done(manifest))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
