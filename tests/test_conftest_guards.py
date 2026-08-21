"""Тесты на само заграждение (`tests/conftest.py`).

Заграждение — тоже код, и его поломка не видна ни по одному падающему
тесту: набор останется зелёным, просто снова начнёт ходить в живую сеть,
спать по-настоящему и читать боевой корпус из рабочей копии. Поэтому у
каждой из трёх fixture есть тест, который проверяет её действие напрямую.
"""
import time
import urllib.request
from pathlib import Path

import pytest

from pipeline import fetcher, mirror, mirror_blog, mirror_faq, run


def test_network_is_blocked_by_default():
    with pytest.raises(RuntimeError, match="попытался выйти в сеть"):
        urllib.request.urlopen("http://example.com/")


def test_pipeline_network_call_is_blocked_too():
    # Не абстрактный urlopen, а реальный путь конвейера: `cdx_snapshots`
    # ловит NETWORK_ERRORS, но RuntimeError заграждения ими не покрыт —
    # значит забытая подмена видна как падение, а не как поход в сеть.
    with pytest.raises(RuntimeError, match="попытался выйти в сеть"):
        fetcher.cdx_snapshots("http://example.com/x.jpg")


def test_sleep_is_replaced_and_recorded(no_sleep):
    fetcher.TokenBucketPacer().wait()
    assert len(no_sleep.calls) == 1
    assert no_sleep.calls[0] > 0        # пауза запрошена — просто не отсижена
    time.sleep(3)
    assert no_sleep.calls[-1] == 3


@pytest.mark.parametrize("module,attr", [
    (run, "DEFAULT_SITE_ROOT"), (run, "DEFAULT_SITE_MANIFEST"), (run, "DEFAULT_PAGES"),
    (run, "DEFAULT_DB"), (run, "DEFAULT_WIKI"), (run, "DEFAULT_ASSETS_MANIFEST"),
    (mirror, "DEFAULT_ASSETS_ROOT"), (mirror_faq, "DEFAULT_ASSETS_MANIFEST"),
    (mirror_blog, "DEFAULT_ASSETS_ROOT"),
])
def test_default_paths_do_not_point_into_the_working_copy(module, attr):
    value = Path(getattr(module, attr))
    # Путь уведён в tmp: и не существует, и лежит вне рабочей копии.
    assert not value.exists()
    assert Path.cwd() not in value.parents
