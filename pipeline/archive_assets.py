"""Файлы картинок из архива Ф0/Ф1: индекс, поиск и отражение в базе.

Картинки FAQ и блогов никогда не качались отдельно (сеть в задачах 6/7 не
трогали вовсе), но часть их адресов — свой хост (`upload/blog/...`), и такие
файлы уже лежали в архиве прошлой фазы: `data/raw/archive/manifest-assets.
jsonl` + `data/raw/archive/assets/`. Логика «найти файл по адресу» появилась
в `mirror_faq` первой и жила там, хотя ничего специфичного для FAQ в ней нет
— это было отмечено в его докстринге как долг. Модуль забирает её к себе,
потому что теперь у неё два потребителя, а не один:

- генератор зеркала (`mirror_faq`/`mirror_blog`) — чтобы скопировать файл в
  вики и поставить вставку;
- `sync_local_paths` — чтобы в базе (`faq_images.local_path`,
  `blog_images.local_path`) стоял ответ на вопрос «уцелела ли эта картинка».

Оба идут через ОДНУ функцию `find`, и это главное свойство модуля: ответ базы
и содержимое вики не могут разойтись, потому что считаются одним кодом.

Почему это понадобилось (находка ре-ревью). До этого модуля `local_path` в
обеих таблицах был NULL у ВСЕХ строк (0 из 232 у FAQ, 0 из 437 у блогов),
хотя в вики стояли 105 + 296 настоящих вставок: зеркало находило файл через
манифест, а колонку не заполнял никто и никогда. Исполнитель Ф3 спросил бы
базу «какие картинки уцелели», получил бы ноль при 401 уцелевшей и решил бы,
что добор провалился. Это тот же класс, что уже кусал фазу однажды
(`assets_state.sync_to_db` не звался при пересборке, и все вложения форума
числились утраченными) — с той же развязкой: истина на диске, база — её
отражение, и отражение обязано восстанавливаться при каждой загрузке.

Значение `local_path` — путь ВНУТРИ архива (`upload/blog/84b/x.jpg`), ровно
как `attachments.local_path` — путь внутри каталога добора. Не путь в вики:
вики пере-генерируема, а этот путь отвечает на вопрос про наличие файла и
проверяется без вики вовсе.
"""
import json
import re
import urllib.parse
from pathlib import Path

DEFAULT_MANIFEST = Path("data/raw/archive/manifest-assets.jsonl")
DEFAULT_ROOT = Path("data/raw/archive/assets")


def normalize_path(url: str) -> str:
    """Путь файла независимо от хоста/регистра/percent-encoding/задвоенных
    слэшей — так же, как реально лежит `path` в `manifest-assets.jsonl`
    (см. task-6-report.md: `.../bcc//p1000089.jpg` в URL, `.../bcc/
    p1000089.jpg` на диске — двойной слэш там коллапсирует).
    """
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path).lstrip("/")
    return re.sub(r"/+", "/", path)


def load_index(manifest_path: Path) -> set[str]:
    """Пути файлов, которые манифест архива обещает."""
    idx: set[str] = set()
    p = Path(manifest_path)
    if not p.exists():
        return idx
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        path = rec.get("path")
        if path:
            idx.add(re.sub(r"/+", "/", path))
    return idx


def find(url: str, index: set[str], root: Path) -> str | None:
    """Путь файла ВНУТРИ архива, если он есть и в манифесте, и на диске.

    `None` — честная утрата: либо адрес в архив не попадал, либо манифест
    обещает файл, которого на диске нет. Обе проверки обязательны: манифест
    и диск расходятся (тот же довод, что в `assets_state.sync_to_db`, где
    статус `ok` без файла на диске становится `lost`).
    """
    rel = normalize_path(url)
    if rel not in index:
        return None
    if not (Path(root) / rel).exists():
        return None
    return rel


def sync_local_paths(conn, manifest: Path = DEFAULT_MANIFEST,
                     root: Path = DEFAULT_ROOT) -> dict[str, int]:
    """Проставить `local_path` в `faq_images`/`blog_images` по архиву.

    Зовётся после загрузчиков (`parse_faq.load_all`/`parse_blog.load_all`) —
    в том числе внутри `ingest`/`all`, а не только отдельной командой:
    загрузчики пересоздают строки картинок при каждом прогоне, и без этого
    шага `--rebuild` возвращал бы колонку в NULL. Ровно та же схема, что у
    `assets_state.sync_to_db` для вложений форума.

    Идемпотентно и не зависит от порядка: значение выводится только из
    манифеста архива и диска, а не из предыдущего состояния базы. Утраченным
    строкам пишется NULL явно — иначе исчезнувший из архива файл остался бы
    в базе «уцелевшим» навсегда.
    """
    index = load_index(manifest)
    stats = {"faq_ok": 0, "faq_lost": 0, "blog_ok": 0, "blog_lost": 0}
    for table, prefix, key in (("faq_images", "faq", ("engine", "nr")),
                                ("blog_images", "blog", ("blog", "post_id"))):
        rows = conn.execute("SELECT id, url FROM %s" % table).fetchall()
        for row_id, url in rows:
            rel = find(url or "", index, root)
            conn.execute("UPDATE %s SET local_path = ? WHERE id = ?" % table, (rel, row_id))
            stats["%s_%s" % (prefix, "ok" if rel else "lost")] += 1
    conn.commit()
    return stats
