"""Добор разделов сайта, которых в архиве нет вовсе: FAQ и блоги (задача 5,
Ф2 «Добор»). Форум мы качали раньше (Ф0/Ф1); FAQ и блоги — отдельные разделы
того же сайта, отредактированные людьми, в архив попавшие впервые здесь.

## Объёмы и что реально лежит под этими адресами

Замер по CDX 20.08.2026 (см. `task-5-report.md`, "Отсев служебных адресов —
разбор с цифрами"): FAQ — 557 адресов со статусом 200 под префиксом
`subaru-faq.ru/faq/`, блоги — 2780 под `subaru-faq.ru/blogs/index.php`. Оба
числа — это то, что вернул CDX, а НЕ то, что реально стоит качать: в обоих
разделах много служебного мусора и точных дублей одной и той же страницы
под разными query-параметрами (печатная версия, подсветка результата
поиска, якорь на конкретный комментарий).

FAQ (557 адресов) состоит из ДВУХ движков разом (сайт мигрировал, архив
хранит снимки обоих):
  - 504 адреса — современный Bitrix (`/faq/index.php?ELEMENT_ID=N` —
    отдельный вопрос-ответ; `?SECTION_ID=N` — категория, вопросов не
    содержит), разметка ответа — `div.catalog-element`;
  - 44 адреса — старый самописный движок (`/faq/faq.php?display=faq&nr=N&
    catnr=C&prog=P&lang=ru`), разметка — `td.question`/`td.answer` (метка,
    затем текст — см. `faq_content_probe`).
Из этого важный вывод: признак содержимого ОБЯЗАН узнавать ОБА движка —
проверка только `td.answer` (как изначально предполагалось по разметке
одной живой страницы) отбраковала бы 504 из 557 адресов (91%) как "нет
содержимого", хотя там есть настоящий ответ, просто в другой разметке.

Блоги (2780 адресов) — движок Bitrix "Blog": `page=post` — отдельная
запись, `page=blog` (+ `category`/`month`/`day`/`year`) — лента/категория/
календарь (список ЗАПИСЕЙ, каждая обёрнута в тот же `div.blog-post`, что и
одиночная запись — проверено вживую, см. `blogs_content_probe`).

## Отсев служебных адресов — по факту разметки, не по догадке

Бриф ожидал служебные адреса вида `login`/`register`/`search`/`mode=write`
внутри самого раздела FAQ — на живых данных таких там НЕТ вовсе: `/auth/` и
`/search/` живут под другими префиксами пути, наш `matchType=prefix` по
`subaru-faq.ru/faq/` их не заденет структурно. Реальный мусор оказался
другим (см. `_FAQ_ASSET_MARKERS`/`_FAQ_NOISE_ACTIONS` и `_BLOGS_SERVICE_PAGES`
ниже) — категории найдены просмотром выгрузки CDX глазами и подтверждены
живой проверкой образцов (что реально лежит под спорными query-параметрами
вроде `page=user`/`page=history`), а не предположением по названию параметра.

Что НЕ отсеивается на этом шаге и почему: категорийные/листинговые страницы
(`SECTION_ID`, `list=category`/`list=subcategory`, `page=blog` без
`post_id`) — это не служебный мусор (не форма входа/поиска/правки), а
страницы БЕЗ собственного ответа/записи. Их не нужно вычёркивать из плана
руками: `content_probe` при скачивании честно определит "нет содержимого"
и так же честно это отметит — вычёркивать их из плана было бы равносильно
предсказанию результата probe до факта, а часть из них (например,
`page=history`) на живой проверке НЕОЖИДАННО оказалась с содержимым (см.
отчёт).

## Дедуп по нормализованному URL

И `print=Y` (печатная версия), и `sphrase_id=N` (подсветка фразы поиска на
той же странице), и `commentId=N` (якорь на комментарий) — не другой
контент, а ТА ЖЕ страница с другим отображением. На боевых данных дедуп по
нормализованному ключу (без этих параметров) сокращает FAQ 543->249 (54%),
блоги 1965->1273 (35%) — качать все варианты значило бы удвоить-утроить
время суточного прогона без единого нового ответа/записи в вики.
"""
import hashlib
import json
import logging
import urllib.parse
from pathlib import Path

from pipeline import assets_state, fetcher

_LOG = logging.getLogger(__name__)
_PROGRESS_EVERY = 50

DEFAULT_PLAN_ROOT = Path("data/raw/site")

FAQ_PREFIX = "subaru-faq.ru/faq/"
BLOGS_PREFIX = "subaru-faq.ru/blogs/index.php"

# --- FAQ: что отсеиваем на этапе плана -------------------------------------

# Статические спутники раздела (иконки/CSS шаблона FAQ) — не HTML-страницы с
# вопросом-ответом, добираются (если вообще нужны) как картинки, не здесь.
_FAQ_ASSET_SUFFIXES = (".css",)


def _faq_is_noise(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    path = parts.path
    if "/gfx/" in path or path.endswith(_FAQ_ASSET_SUFFIXES):
        return True
    qs = urllib.parse.parse_qs(parts.query)
    # Экшены каталога Bitrix (добавить в корзину/купить) — прицепом к
    # ELEMENT_ID остались в архиве с шаблона FAQ-как-каталога, к самому
    # вопросу-ответу отношения не имеют (см. отчёт задачи 5).
    if qs.get("action", [None])[0] in ("ADD2BASKET", "BUY"):
        return True
    # Буквально из брифа (mode=write/login/register/search) — на префиксе
    # /faq/ вживую не встретилось (см. докстринг модуля), но проверка не
    # бесплатной ценой: если сайт когда-нибудь начнёт отдавать такие
    # адреса и под этим префиксом, они не должны попасть в план.
    if qs.get("mode", [None])[0] == "write":
        return True
    if "login" in qs or "register" in qs or "/auth" in path or "search" in path.lower():
        return True
    return False


# Параметры, которые меняют ОТОБРАЖЕНИЕ уже учтённой страницы, а не её
# содержимое — печатная версия, подсветка фразы поиска, cache-busting
# edit-mode параметры Bitrix (см. докстринг модуля, "Дедуп").
_FAQ_DROP_PARAMS = frozenset({
    "print", "sphrase_id", "clear_cache", "bitrix_include_areas", "bitrix_show_mode"})


def _faq_kind(url: str) -> str:
    """Разметка плана — не только "качать/не качать" (это уже сделал
    `_faq_is_noise`), но и "чего вообще ждать": `"answer"` — отдельный
    вопрос-ответ (в любом из двух движков, см. докстринг модуля, "Главная
    находка"), `"listing"` — категория/старый список без своего ответа
    (`SECTION_ID`, `list=category|subcategory`) — то, что почти наверняка
    даст `"empty"` у `faq_content_probe`, и это ОЖИДАЕМЫЙ, а не потерянный
    результат (см. отчёт задачи 5, "Что НЕ отсеивается на уровне плана").
    `"other"` — блан/краевые варианты (`proginfo.php` и пустые query),
    контент под вопросом, но не листинг и не подтверждённый ответ.
    """
    p = urllib.parse.urlsplit(url)
    qs = urllib.parse.parse_qs(p.query)
    if p.path == "/faq/index.php":
        if "ELEMENT_ID" in qs:
            return "answer"
        if "SECTION_ID" in qs:
            return "listing"
        return "other"
    if p.path == "/faq/faq.php":
        if qs.get("display", [None])[0] == "faq":
            return "answer"
        if "list" in qs:
            return "listing"
        return "other"
    if p.path == "/faq/proginfo.php":
        return "answer"
    return "other"


# --- Блоги: что отсеиваем на этапе плана -----------------------------------

# `page=` значения, для которых живая проверка (task-5-report.md) показала:
# содержательных блоков `div.blog-post` в теле НЕ бывает вовсе. `history` в
# список НЕ входит намеренно — там `blog-post` реально нашёлся (см. докстринг).
_BLOGS_SERVICE_PAGES = frozenset({"search", "rss", "rss_all", "blog_edit", "user", "group"})


def _blogs_kind(url: str) -> str:
    """`"post"` — отдельная запись (`page=post`), `"listing"` — лента/
    категория/календарь/история (несколько записей-эксцерптов на одной
    странице — см. отчёт задачи 5, "Блоги: 2779 → 1272"). Решение лида:
    ленты качаем, но ВТОРЫМ заходом после отдельных записей (см. порядок в
    `build_list`) — если суточный прогон оборвётся, обрывается менее ценная
    часть, а не наоборот.
    """
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    return "post" if qs.get("page", [None])[0] == "post" else "listing"


def _blogs_is_noise(url: str) -> bool:
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    return qs.get("page", [None])[0] in _BLOGS_SERVICE_PAGES


_BLOGS_DROP_PARAMS = frozenset({"print", "sphrase_id", "commentId"})
# Сознательно НЕ в этом множестве:
#   - `pagen` (нижний регистр, встречается только с `page=post&post_id=`) —
#     пагинация КОММЕНТАРИЕВ под одной и той же записи; сама запись на всех
#     страницах одна и та же, но комментарии — разные, отбрасывать нельзя,
#     иначе план потеряет часть комментариев без права восстановления;
#   - `PAGEN_1` (верхний регистр, `page=history`/`page=group`) — штатный
#     пагинатор Bitrix ЛИСТИНГА: разные значения показывают РАЗНЫЕ записи,
#     а не другой вид той же страницы — дропать было бы неверно по той же
#     причине, что и `pagen` выше, только сильнее (тут теряются не
#     комментарии, а сами записи).


# Приоритет внутри плана: элементы с kind из этого множества идут ПЕРВЫМИ
# (устойчивая сортировка — порядок внутри каждой группы не меняется). Для
# блогов это прямое решение лида ("сперва 498 записей, потом 774 ленты" —
# если прогон оборвётся, теряется менее ценная часть); для FAQ применено по
# аналогии (отдельные ответы раньше категорий) — план и так маленький (249),
# но это не противоречит решению лида и ничего не стоит.
_SECTIONS = {
    "faq": {"prefix": FAQ_PREFIX, "is_noise": _faq_is_noise, "drop_params": _FAQ_DROP_PARAMS,
            "kind_fn": _faq_kind, "priority_kinds": frozenset({"answer"})},
    "blogs": {"prefix": BLOGS_PREFIX, "is_noise": _blogs_is_noise, "drop_params": _BLOGS_DROP_PARAMS,
              "kind_fn": _blogs_kind, "priority_kinds": frozenset({"post"})},
}


def _normalize(url: str, drop_params: frozenset) -> tuple:
    """Ключ дедупа: хост без `www.`/регистра, путь, параметры без "шумных"
    (см. `_FAQ_DROP_PARAMS`/`_BLOGS_DROP_PARAMS`) — отсортированы, чтобы
    порядок параметров в самом URL не создавал ложных "разных" страниц.
    """
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    qs = urllib.parse.parse_qs(p.query)
    for k in drop_params:
        qs.pop(k, None)
    items = tuple(sorted((k, tuple(sorted(v))) for k, v in qs.items()))
    return (host, p.path, items)


def local_path(section: str, url: str) -> str:
    """Путь внутри `data/raw/site/`: раздел + устойчивый хэш URL. Хэш, а не
    производное от ELEMENT_ID/post_id — те есть не у всех адресов раздела
    (категории/листинги их не несут в удобном для имени файла виде), а хэш
    от полного URL стабилен всегда (тот же приём, что и `fetch_assets.
    local_name` для картинок).
    """
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return "%s/%s.html" % (section, digest)


def build_list(section: str) -> list[dict]:
    """План скачивания раздела (`"faq"` или `"blogs"`) по CDX: один запрос
    метаданных на раздел (`fetcher.cdx_snapshots(..., match_type="prefix")`,
    страница/пагинация внутри — см. `fetcher.py`), тела снимков НЕ тянет.

    Возвращает список словарей `{"section", "url", "ts", "local_path",
    "kind"}` — уже без служебного мусора и без дублей одной и той же
    страницы под разными query-параметрами отображения (см. докстринг
    модуля). `kind` — что именно за адрес (`_faq_kind`/`_blogs_kind`):
    нужен и для честного отчёта (сколько в плане ОЖИДАЕТСЯ ответов/записей,
    а не только "адресов"), и для порядка — список отсортирован СТАБИЛЬНО
    так, что приоритетный `kind` (`_SECTIONS[section]["priority_kinds"]`)
    идёт первым, а порядок внутри каждой группы не меняется. Для блогов это
    прямое решение лида: сперва отдельные записи, потом ленты — обрыв
    суточного прогона потеряет менее ценную часть.

    Метка снимка (`ts`) у каждого адреса — САМАЯ РАННЯЯ из имеющихся, и это
    сознательно (Ruling 32; механика и цифры — в комментарии внутри
    префиксной ветки `fetcher.cdx_snapshots`). Коротко: у страниц FAQ 503 и
    176 свежайшие снимки 2022 года не разбираются вовсе — сайт к тому
    времени отдавал другую разметку, — и раздел спасён именно тем, что в
    план попали снимки 2010 года. Кто "починит" знак лимита по аналогии с
    точечной ветвью, сломает FAQ; цена решения — потерянные поздние
    комментарии блогов (279 из 528 записей сняты в пределах 30 дней от
    публикации).
    """
    cfg = _SECTIONS[section]
    rows = fetcher.cdx_snapshots(cfg["prefix"], match_type="prefix")
    seen: dict[tuple, dict] = {}
    for ts, url in rows:
        if cfg["is_noise"](url):
            continue
        key = _normalize(url, cfg["drop_params"])
        if key in seen:
            continue
        seen[key] = {"section": section, "url": url, "ts": ts,
                     "local_path": local_path(section, url),
                     "kind": cfg["kind_fn"](url)}
    priority = cfg["priority_kinds"]
    return sorted(seen.values(), key=lambda item: item["kind"] not in priority)


def _plan_path(section: str, root: Path) -> Path:
    return Path(root) / ("plan-%s.json" % section)


def save_plan(section: str, plan: list[dict], root: Path = DEFAULT_PLAN_ROOT) -> Path:
    """Сохраняет план на диск ЗАРАНЕЕ, одним файлом на раздел — суточный
    прогон может оборваться и перезапуститься, а второй запрос к CDX за тем
    же списком (вместо чтения уже сохранённого) удвоил бы нагрузку на архив
    без всякой пользы (см. `global-constraints.md`).
    """
    p = _plan_path(section, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load_plan(section: str, root: Path = DEFAULT_PLAN_ROOT) -> list[dict]:
    """Читает план, сохранённый `save_plan`. Отсутствующий файл — явная
    ошибка (`FileNotFoundError` из `Path.read_text`), а не пустой план: молча
    скачивать "план из нуля адресов" и получить пустую статистику опаснее,
    чем упасть с понятной причиной (тот же принцип, что и у `run.py` для
    отсутствующей базы в `coverage`/`mirror`).
    """
    p = _plan_path(section, root)
    return json.loads(p.read_text(encoding="utf-8"))


# --- признак содержимого: свой для FAQ и для блогов ------------------------

def faq_content_probe(data: bytes) -> bool:
    """Есть ли в странице настоящий ответ FAQ — в ЛЮБОМ из двух движков,
    архивированных на этом сайте (см. докстринг модуля):

    - современный Bitrix (504/557 адресов) — `div.catalog-element`;
    - старый самописный движок (44/557) — `td.question` СЛЕДОМ за
      `td.answer` (метка, затем текст, как описал лид) — оба класса
      должны присутствовать разом, само по себе слово "question" или
      "answer" по отдельности ничего не доказывает.

    Категорийные/листинговые страницы (`SECTION_ID`, `list=category`) не
    несут ни одной из этих меток — с этим probe’ом они честно определяются
    как "нет содержимого" (см. `test_faq_content_probe_rejects_section_
    listing_without_an_answer`), что и требуется: план их не вычёркивает
    заранее, отсев происходит здесь.
    """
    if b'class="catalog-element"' in data:
        return True
    return b'class="question"' in data and b'class="answer"' in data


def blogs_content_probe(data: bytes) -> bool:
    """Есть ли в странице хотя бы один блок записи блога.

    `class="blog-post"` — байтовая проверка ищет ТОЧНУЮ кавычку сразу после
    `blog-post` (родственные классы вида `blog-post-title`/`blog-post-
    content`/`blog-post-comments-link` не совпадут — после `blog-post` там
    идёт `-`, а не закрывающая кавычка). Проверено вживую: страница
    одиночной записи (`page=post`) несёт этот блок один раз, лента/
    категория/календарь (`page=blog`) — по разу на КАЖДУЮ показанную запись
    (тоже "есть содержимое" — это не пустая листалка), а `page=user`/`page=
    group` (списки блогов без единой записи внутри) — ни разу.

    Это булев признак ("есть хоть один блок записи"), а не классификатор —
    он НЕ отличает одиночную запись от ленты из нескольких эксцерптов: на
    образцах (`tests/fixtures/blog_post.html` — 1 блок, `blog_listing_home.
    html` — 3 блока) probe возвращает `True` для обоих (см. `test_blogs_
    content_probe_cannot_tell_a_single_post_from_a_listing_of_excerpts`).
    Различать "это полная запись" от "это лента" — задача `_blogs_kind`
    (`"post"`/`"listing"`, сохраняется в план и переживает на диске), не
    этой функции: смешивать две ортогональные проверки в одной было бы
    той самой путаницей, которой лид опасался.
    """
    return b'class="blog-post"' in data


# Статусы, при которых адрес НЕ запрашивается повторно. `failed` сюда не
# входит сознательно: это утверждение о прогоне («сеть не отдала тела»), а не
# об архиве. То же правило у добора картинок — `fetch_assets.
# TERMINAL_STATUSES`/`RETRY_ON_DOWNLOAD` (дефект C1 итогового ревью Ф2).
TERMINAL_STATUSES = ("ok", "empty")

_CONTENT_PROBES = {"faq": faq_content_probe, "blogs": blogs_content_probe}


def _try_candidates(candidates, probe):
    """Пробует снимки по очереди, пока не найдёт снимок, проходящий `probe`.

    Тот же приём, что и в `fetch_assets._try_candidates` (не вынесен в общий
    модуль намеренно — риск задеть уже протестированный код добора картинок
    ради малого дублирования не стоил того на этом шаге, см. отчёт задачи 5).
    Возвращает `(данные, saw_content)`: `saw_content` истинно, если хоть одно
    тело реально скачалось, но не прошло проверку содержимого — нужно, чтобы
    отличить "empty" (контента не было) от "failed" (сеть не отдала ничего)
    без второго обращения к CDX.
    """
    saw_content = False
    for ts, orig in candidates:
        candidate = fetcher.fetch_snapshot(ts, orig)
        if candidate is None:
            continue
        if fetcher.looks_empty(candidate, content_probe=probe) is not None:
            saw_content = True
            continue
        return candidate, saw_content
    return None, saw_content


def fetch_all(plan: list[dict], dest: Path, manifest: Path, limit: int | None = None) -> dict[str, int]:
    """Скачивает страницы плана в `dest`, отмечая каждую в `manifest` — та
    же схема состояния, что и добор картинок (`assets_state`): истина на
    диске (манифест + сами файлы), а не в памяти процесса, поэтому обрыв
    суточного прогона теряет самое большее одну незаписанную страницу.

    Уже отмеченные `ok`/`empty` адреса НЕ запрашиваются повторно
    (`TERMINAL_STATUSES`, см. `test_fetch_all_is_idempotent_and_skips_already_
    done_urls`) — только `failed` (или вовсе не встречавшиеся ранее)
    считаются целью прогона. То же правило теперь и у добора картинок
    (`fetch_assets.RETRY_ON_DOWNLOAD`, дефект C1 итогового ревью Ф2): до
    правки два модуля решали этот вопрос противоположно.
    Признак содержимого свой для каждого элемента плана — `item["section"]`
    выбирает FAQ- или блоговый `content_probe` (см. `_CONTENT_PROBES`), один
    прогон может смешивать обе секции разом.

    `limit` — как и у `fetch_assets` (`--limit` в `run.py`), для пробного
    прогона на нескольких адресах перед суточным: ограничивает список ЦЕЛЕЙ
    (уже отфильтрованных по манифесту), не сам план.

    Сперва пробует метку снимка, сохранённую в самом плане (`item["ts"]`),
    напрямую (`fetcher.fetch_snapshot`, без обращения к CDX). Только если
    этот снимок пустышка или не отдался — запрашивается полная история
    (`fetcher.cdx_snapshots(url)`, без `match_type` — точный поиск по
    ОДНОМУ URL, не по префиксу), и то один раз — тот же приём, что и в
    `fetch_assets.download` (см. его докстринг о накопленной стоимости
    второго CDX-вызова на масштабе тысяч адресов).
    """
    stats = {"ok": 0, "empty": 0, "failed": 0}
    pacer = fetcher.TokenBucketPacer()
    known = assets_state.load(manifest)
    targets = [item for item in plan
               if known.get(item["url"], {}).get("status") not in TERMINAL_STATUSES]
    if limit is not None:
        targets = targets[:limit]
    total = len(targets)
    for i, item in enumerate(targets, 1):
        probe = _CONTENT_PROBES[item["section"]]
        url = item["url"]
        saw_content = False

        data = None
        if item.get("ts"):
            data, seen = _try_candidates([(item["ts"], url)], probe)
            saw_content = saw_content or seen
        if data is None:
            data, seen = _try_candidates(fetcher.cdx_snapshots(url), probe)
            saw_content = saw_content or seen

        if data is None:
            reason = "empty" if saw_content else "failed"
            assets_state.record(manifest, url, None, reason)
            stats[reason] += 1
            pacer.note(reason != "failed")
        else:
            rel = item["local_path"]
            path = Path(dest) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            assets_state.record(manifest, url, rel, "ok")
            stats["ok"] += 1
            pacer.note(True)

        if i % _PROGRESS_EVERY == 0 or i == total:
            _LOG.info("добор сайта: %d/%d — ok=%d empty=%d failed=%d",
                       i, total, stats["ok"], stats["empty"], stats["failed"])
        pacer.wait()
    return stats
