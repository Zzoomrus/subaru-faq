"""Скачивание из Wayback: индексация через CDX и загрузка снимков.

Темп задаёт сам архив: снимки отдаются через токен-бакет, около 2 стр/мин на IP.
Гнать быстрее бесполезно — проверено в Ф0: залп из 8 запросов не даёт ничего
сверх залпа из 4, только жжёт трафик.

О `looks_empty` и антибот-маркере (важно для задач 2-8, читающих этот модуль):
маркеры `ctSetCookie`/`ctMouseData` — JS сайтового антиспам-виджета (CleanTalk),
а НЕ признак антибот-заглушки. На корпусе Ф0/Ф1 (5938 файлов) он встречается
на 1758 страницах, из которых только 10 — настоящие антибот-заглушки
(подтверждено в Ф0/Ф1, docs/coverage-notes.md); остальные 1748 — обычные
страницы с полноценным контентом, которые просто тоже несут этот виджет в
шаблоне (сайт на Bitrix, виджет в `<head>` с ~2016 года). Отличить эти два
случая по байтам/размеру не выходит: 10 настоящих заглушек — 23-30 КБ, и в
том же диапазоне 22-35 КБ лежат вперемешку 328 файлов, часть с реальным
контентом. Поэтому в `looks_empty` маркер CleanTalk НЕ используется вовсе —
универсального байтового признака пустоты для HTML нет и попытка его
придумать уже стоила один цикл разработки.

`looks_empty` проверяет только то, что верно всегда: разметку страницы
ошибки БД и общий порог размера. Признак "есть ли тут содержимое" зависит от
шаблона конкретного типа страниц (форум — блок `div.forum-post-text`, FAQ —
`td.answer`, блоги — класс семейства `blog-*`) и передаётся вызывающим кодом
через параметр `content_probe` — вызываемый объект `bytes -> bool`. Для
двоичных ответов (картинки) используй `looks_empty_binary`: там порог по
размеру бессмыслен (валидный маленький PNG/JPEG весит меньше 1024 байт),
признаком служит валидность самого формата — тоже через `content_probe`.
"""
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
NETWORK_ERRORS = (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                  OSError, HTTPException, ValueError)


def _get(url: str, timeout: int = 90) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if r.status == 200 else None


def cdx_snapshots(url: str, retries: int = 6) -> list[tuple[str, str]]:
    """Все снимки URL со статусом 200, свежие первыми."""
    q = urllib.parse.urlencode({
        "url": url, "output": "json", "fl": "timestamp,original",
        "filter": "statuscode:200", "limit": "50"})
    for attempt in range(retries):
        try:
            raw = _get("https://web.archive.org/cdx/search/cdx?" + q)
            rows = json.loads(raw)[1:] if raw else []
            return [(ts, orig) for ts, orig in sorted(rows, reverse=True)]
        except NETWORK_ERRORS:
            time.sleep(3 * (attempt + 1))
    return []


def fetch_snapshot(ts: str, url: str, retries: int = 4) -> bytes | None:
    for attempt in range(retries):
        try:
            return _get("https://web.archive.org/web/%sid_/%s" % (ts, url))
        except NETWORK_ERRORS:
            time.sleep(3 * (attempt + 1))
    return None


def looks_empty(data: bytes, content_probe=None) -> str | None:
    """Признак того, что снимок HTML-страницы есть, а содержимого в нём нет.

    Порядок проверок: сначала точная, проверенная на реальном архиве
    сигнатура страницы ошибки БД (db_error), затем — если вызывающий код
    передал `content_probe` — предметная проверка наличия содержимого
    (no_content), и только потом общий размерный порог (too_small).

    `content_probe`: необязательный вызываемый объект `bytes -> bool`,
    отвечающий "есть ли тут содержимое". Признак зависит от шаблона
    конкретного типа страниц (форум — `div.forum-post-text`, FAQ —
    `td.answer`, блоги — класс `blog-*`) — универсального байтового
    признака нет, поэтому модуль скачивания его не придумывает сам, это
    отдаёт вызывающему коду. В частности, антибот-маркер CleanTalk
    (`ctSetCookie`/`ctMouseData`) сюда сознательно не входит: это виджет
    сайта на ~30% обычных страниц, а не признак заглушки (см. докстринг
    модуля).
    """
    if data is None:
        return "too_small"
    # Точная разметка настоящей страницы ошибки БД (проверено на архиве:
    # 1/1 совпадение на 5938 файлах). Просто подстрока "DB query error" без
    # тегов даёт 2 ложных срабатывания — это реальные посты форума, где
    # пользователи ЦИТИРУЮТ увиденную ими ошибку в тексте своего сообщения.
    if b"<b>DB query error.</b>" in data:
        return "db_error"
    if content_probe is not None and not content_probe(data):
        return "no_content"
    if len(data) < 1024:
        return "too_small"
    return None


def looks_empty_binary(data: bytes, content_probe=None) -> str | None:
    """Признак пустышки для двоичных ответов (картинки и т.п.).

    Байтовый порог "too_small" из `looks_empty` здесь неприменим: валидный
    маленький PNG/JPEG весит меньше 1024 байт, а порог в килобайт для
    двоичных данных бессмыслен в принципе — признаком пустоты служит не
    размер, а валидность самого формата. Эту проверку делает вызывающий код
    (например, попытка декодировать байты как изображение) и передаёт её
    сюда через `content_probe` (`bytes -> bool`, "есть ли валидное
    содержимое"). Без `content_probe` функция может утверждать только
    полное отсутствие данных.
    """
    if data is None:
        return "too_small"
    if content_probe is not None and not content_probe(data):
        return "no_content"
    return None


class TokenBucketPacer:
    """Пауза между запросами по текущей доле успехов в последних 30 попытках."""

    def __init__(self) -> None:
        self._window: list[bool] = []

    def note(self, ok: bool) -> None:
        self._window.append(ok)
        del self._window[:-30]

    def delay(self) -> float:
        rate = sum(self._window) / len(self._window) if self._window else 0.5
        base = 2.5 if rate > 0.5 else 4.0 if rate > 0.2 else 8.0 if rate > 0.05 else 15.0
        return base * random.uniform(0.7, 1.3)

    def wait(self) -> None:
        time.sleep(self.delay())
