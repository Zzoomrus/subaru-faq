import json
import urllib.error
from unittest.mock import patch, MagicMock
from pathlib import Path

from pipeline import fetcher

FIX = Path(__file__).parent / "fixtures"

# --- Дословно из брифа задачи 1 (task-1-brief.md, Шаг 1) — не менять без ---
# --- согласования: ревьюеры прошлой фазы дважды ловили на разночтениях. ---
# --- ИСКЛЮЧЕНИЕ: test_looks_empty_detects_antibot переименован и переписан ---
# --- по прямому решению лида (task-1-report.md, раздел «Правка: признак   ---
# --- содержимого передаёт вызывающий») — гипотеза брифа «маркер           ---
# --- ctSetCookie/ctMouseData = антибот-заглушка» опровергнута на корпусе: ---
# --- это виджет CleanTalk, вшитый в ~30% обычных страниц сайта.          ---

def test_looks_empty_detects_db_error():
    assert fetcher.looks_empty("<b>DB query error.</b> Please try later.".encode("cp1251")) == "db_error"

def test_looks_empty_antibot_marker_alone_is_no_longer_a_signal():
    # Было: == "antibot". Маркер ctSetCookie/ctMouseData — JS антиспам-виджета
    # CleanTalk, встречается на ~30% обычных страниц сайта (1758 из 5938 в
    # корпусе Ф0/Ф1) — самостоятельным признаком пустоты быть не может.
    # Короткая строка всё равно ловится общим порогом размера (too_small),
    # но НЕ из-за маркера антибота — это следующий тест ниже доказывает,
    # добавляя маркеру настоящий контент.
    assert fetcher.looks_empty(b"<script>ctSetCookie(); ctMouseData()</script>") == "too_small"

def test_looks_empty_page_with_antibot_marker_and_real_content_is_not_empty():
    # Главный кейс задания: CleanTalk-виджет соседствует с настоящим
    # содержимым форума — это НЕ пустышка, ни без probe, ни с ним.
    page = ("<html><head><script>ctSetCookie(); ctMouseData();</script></head>"
            "<body><div class='forum-post-text'>" +
            "Течь сальника коленвала лечится заменой. " * 40 +
            "</div></body></html>").encode("cp1251")
    probe = lambda d: b"forum-post-text" in d
    assert fetcher.looks_empty(page) is None
    assert fetcher.looks_empty(page, content_probe=probe) is None

def test_looks_empty_detects_too_small():
    assert fetcher.looks_empty(b"<html></html>") == "too_small"

def test_looks_empty_passes_real_page():
    page = ("<html><body>" + "Течь сальника коленвала лечится заменой. " * 40 + "</body></html>").encode("cp1251")
    assert fetcher.looks_empty(page) is None

def test_pacer_slows_down_after_failures():
    p = fetcher.TokenBucketPacer()
    fast = p.delay()
    for _ in range(30):
        p.note(False)
    assert p.delay() > fast

# --- Дополнительно к дословным тестам брифа ---

def test_looks_empty_real_db_error_fixture():
    # Настоящая заглушка ошибки БД из архива (data/raw/archive/broken/read_18_41771_1.html,
    # скопирована в фикстуры ещё в Ф0/Ф1 как broken_db_error.html).
    data = (FIX / "broken_db_error.html").read_bytes()
    assert fetcher.looks_empty(data) == "db_error"

def test_looks_empty_real_antibot_fixture_without_probe_is_not_flagged():
    # Настоящая антибот-заглушка из архива (одна из 10 известных, задача 4
    # Ф0/Ф1), но БЕЗ content_probe. Заглушки весят 23-30 КБ — выше порога
    # too_small, а маркер antibot больше не самостоятельный признак. Это и
    # есть цена отказа от 30% ложных срабатываний: без probe от вызывающего
    # кода fetcher сам эту заглушку не отличит от обычной страницы.
    data = (FIX / "message_bot_challenge.html").read_bytes()
    assert fetcher.looks_empty(data) is None

def test_looks_empty_real_antibot_fixture_with_forum_probe_is_no_content():
    # С forum-специфичным probe (как реально будет использовать код,
    # скачивающий форум) та же заглушка распознаётся верно.
    data = (FIX / "message_bot_challenge.html").read_bytes()
    probe = lambda d: b"forum-post-text" in d
    assert fetcher.looks_empty(data, content_probe=probe) == "no_content"

def test_looks_empty_content_probe_no_content_returns_no_content_even_when_large():
    page = ("<html><body>" + "x" * 2000 + "</body></html>").encode("cp1251")
    assert fetcher.looks_empty(page, content_probe=lambda d: False) == "no_content"

def test_looks_empty_content_probe_true_still_enforces_size_threshold():
    assert fetcher.looks_empty(b"<html></html>", content_probe=lambda d: True) == "too_small"

def test_looks_empty_bare_db_error_text_is_not_a_false_positive():
    # На архиве нашлись 2 реальных поста форума, где пользователи ЦИТИРУЮТ
    # увиденную ими ошибку "DB query error." простым текстом, без <b>-разметки
    # реальной страницы ошибки. Такое не должно классифицироваться как db_error.
    page = ("<html><body>" + "Зашёл на форум сегодня и опять DB query error. "
            "Please try later. Достало уже чиниться раз в неделю. " * 20 +
            "</body></html>").encode("cp1251")
    assert fetcher.looks_empty(page) is None

def test_pacer_reaches_max_delay_after_sustained_failures():
    # Требование из брифа фазы: при полном отсутствии успехов пауза должна
    # дорасти до базовых 15 секунд (с учётом джиттера 0.7-1.3), а не застрять
    # на маленьком значении.
    p = fetcher.TokenBucketPacer()
    for _ in range(30):
        p.note(False)
    assert p.delay() >= 15 * 0.7

# --- looks_empty_binary: вариант для двоичных ответов (картинки и т.п.) ---
# --- Порог "мало байт" здесь бессмыслен — валидный маленький PNG/JPEG   ---
# --- весит меньше 1024 байт. Признаком служит валидность самого формата, ---
# --- её проверяет content_probe вызывающего кода (задача 2 — картинки). ---

def test_looks_empty_binary_none_data_is_too_small():
    assert fetcher.looks_empty_binary(None) == "too_small"

def test_looks_empty_binary_small_valid_data_without_probe_is_not_empty():
    # Байтовый порог не применяется к двоичным данным: 8 байт — валидный
    # PNG-заголовок, и без probe это не пустышка.
    assert fetcher.looks_empty_binary(b"\x89PNG\r\n\x1a\n") is None

def test_looks_empty_binary_probe_false_is_no_content():
    assert fetcher.looks_empty_binary(b"garbage-not-an-image", content_probe=lambda d: False) == "no_content"

def test_looks_empty_binary_probe_true_passes():
    assert fetcher.looks_empty_binary(b"\x89PNG\r\n\x1a\n", content_probe=lambda d: True) is None

def _cdx_response(rows):
    body = json.dumps([["timestamp", "original"]] + rows).encode("utf-8")
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    resp.status = 200
    resp.read.return_value = body
    return resp

def test_cdx_snapshots_skips_header_and_sorts_fresh_first():
    rows = [["20150101000000", "http://x/"], ["20200601000000", "http://x/"]]
    with patch("pipeline.fetcher.urllib.request.urlopen", return_value=_cdx_response(rows)):
        result = fetcher.cdx_snapshots("http://x/")
    assert result == [("20200601000000", "http://x/"), ("20150101000000", "http://x/")]

def test_cdx_snapshots_empty_when_no_rows():
    with patch("pipeline.fetcher.urllib.request.urlopen", return_value=_cdx_response([])):
        assert fetcher.cdx_snapshots("http://x/") == []

def test_cdx_snapshots_returns_empty_list_after_retries_exhausted():
    with patch("pipeline.fetcher.urllib.request.urlopen",
               side_effect=urllib.error.URLError("boom")), \
         patch("pipeline.fetcher.time.sleep") as sleep_mock:
        result = fetcher.cdx_snapshots("http://x/", retries=3)
    assert result == []
    assert sleep_mock.call_count == 3

def test_fetch_snapshot_returns_bytes_on_success():
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    resp.status = 200
    resp.read.return_value = b"<html>content</html>"
    with patch("pipeline.fetcher.urllib.request.urlopen", return_value=resp):
        data = fetcher.fetch_snapshot("20200101000000", "http://x/")
    assert data == b"<html>content</html>"

def test_fetch_snapshot_returns_none_after_retries_exhausted():
    with patch("pipeline.fetcher.urllib.request.urlopen",
               side_effect=urllib.error.URLError("boom")), \
         patch("pipeline.fetcher.time.sleep") as sleep_mock:
        data = fetcher.fetch_snapshot("20200101000000", "http://x/", retries=2)
    assert data is None
    assert sleep_mock.call_count == 2

def test_fetch_snapshot_retries_then_succeeds():
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    resp.status = 200
    resp.read.return_value = b"ok"
    with patch("pipeline.fetcher.urllib.request.urlopen",
               side_effect=[urllib.error.URLError("boom"), resp]), \
         patch("pipeline.fetcher.time.sleep") as sleep_mock:
        data = fetcher.fetch_snapshot("20200101000000", "http://x/", retries=4)
    assert data == b"ok"
    assert sleep_mock.call_count == 1
