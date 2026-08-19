"""Скачивание из Wayback: индексация через CDX и загрузка снимков.

Темп задаёт сам архив: снимки отдаются через токен-бакет, около 2 стр/мин на IP.
Гнать быстрее бесполезно — проверено в Ф0: залп из 8 запросов не даёт ничего
сверх залпа из 4, только жжёт трафик.

О `looks_empty` и антибот-маркере (важно для задач 2-8, читающих этот модуль):
маркеры `ctSetCookie`/`ctMouseData` — JS сайтового антиспам-виджета (CleanTalk).
На корпусе Ф0/Ф1 (5938 файлов) он встречается на 1758 страницах, из которых
только 10 — настоящие антибот-заглушки (подтверждено в Ф0/Ф1, coverage-notes.md);
остальные 1748 — обычные страницы с полноценным контентом, которые просто тоже
несут этот виджет в шаблоне. Отличить эти два случая по байтам/размеру
не выходит: 10 настоящих заглушек — 23-30 КБ, и в том же диапазоне 22-35 КБ
лежат вперемешку 328 файлов из общего множества, часть с реальным контентом.
Единственный найденный надёжный признак — отсутствие блока `forum-post-text`
в разметке, но это форумная специфика (parse_thread.py уже её использует) и
не годится как общий байтовый критерий для FAQ/картинок/блогов.

Следствие: verdict "antibot" из этой функции надёжен для бинарных ответов
(вместо картинки прилетела HTML-страница испытания) и НЕ надёжен как
самостоятельный вердикт для HTML-страниц сайта — там он лишь advisory-сигнал
"возможно попробовать другой снимок", а не доказательство пустоты. Финальное
решение о пустоте HTML-страницы должен подтверждать разбор конкретного типа
контента (для форума это уже делает parse_thread.py).
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


def looks_empty(data: bytes) -> str | None:
    """Признак того, что снимок есть, а содержимого в нём нет.

    Порядок проверок важен: сначала точные, проверенные на реальном архиве
    сигнатуры (db_error, antibot), и только потом общий размерный порог.
    """
    if data is None:
        return "too_small"
    # Точная разметка настоящей страницы ошибки БД (проверено на архиве:
    # 1/1 совпадение на 5938 файлах). Просто подстрока "DB query error" без
    # тегов даёт 2 ложных срабатывания — это реальные посты форума, где
    # пользователи ЦИТИРУЮТ увиденную ими ошибку в тексте своего сообщения.
    if b"<b>DB query error.</b>" in data:
        return "db_error"
    if b"ctSetCookie" in data or b"ctMouseData" in data:
        return "antibot"
    if len(data) < 1024:
        return "too_small"
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
