"""Заграждение набора тестов: ни одного сетевого обращения и ни одной
настоящей паузы.

Обе fixture — `autouse`, то есть действуют на КАЖДЫЙ тест, включая те,
которые ещё не написаны. Это и есть смысл: до этого файла герметичность
набора держалась на том, что автор каждого теста не забыл подменить
`fetcher.cdx_snapshots`/`fetch_snapshot`. Забыл — тест молча уходил в живой
Wayback: зелёный на машине с интернетом, красный без неё, и медленный на
обеих (итоговое ревью Ф2, находка I4).

`no_network` — запрет `urllib.request.urlopen`. Патчится атрибут САМОГО
модуля `urllib.request`, а не `pipeline.fetcher.urllib.request.urlopen`:
это один и тот же объект, поэтому запрет накрывает любой модуль конвейера
(`fetcher`, будущие), а тесты, которые подменяют `urlopen` сами (см.
`test_fetcher.py` — они проверяют РАЗБОР ответа и строку запроса), просто
перекрывают заглушку своим `patch` внутри теста и работают как раньше.
Тест, которому живая сеть действительно нужна, помечается
`@pytest.mark.allow_network` — сегодня таких нет ни одного, и маркер
существует ровно для того, чтобы такой тест нельзя было завести молча.

`no_sleep` — подмена `time.sleep` на пустышку, тоже на уровне модуля
`time`. Настоящих пауз в наборе было на две минуты из двух минут его
работы: `TokenBucketPacer.wait()` (2,5-19,5 с за вызов) и backoff
`time.sleep(3 * (attempt + 1))` в retry-циклах `fetcher`/`fetch_site` —
логика темпа при этом не проверяется временем ни в одном тесте (там, где
она проверяется, тест подменяет пейсер целиком или сам смотрит на
`sleep_mock.call_args`), так что терять нечего. Записанные вызовы
доступны через `no_sleep.calls` — тест может утверждать «пауза была и
такой длины», не платя за неё секундами.
"""
import time
import urllib.request
from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "allow_network: тесту действительно нужна живая сеть (сегодня таких нет)")
    config.addinivalue_line(
        "markers", "real_data: тесту нужен боевой корпус из рабочей копии (сегодня таких нет)")


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    if request.node.get_closest_marker("allow_network"):
        return

    def _blocked(*args, **kwargs):
        target = args[0] if args else kwargs.get("url")
        raise RuntimeError(
            "тест попытался выйти в сеть: urlopen(%r). Подмени "
            "fetcher.cdx_snapshots/fetch_snapshot/urlopen в самом тесте "
            "(или пометь @pytest.mark.allow_network, если сеть правда нужна)"
            % (getattr(target, "full_url", target),))

    monkeypatch.setattr(urllib.request, "urlopen", _blocked)


class _SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float = 0.0) -> None:
        self.calls.append(seconds)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    recorder = _SleepRecorder()
    monkeypatch.setattr(time, "sleep", recorder)
    return recorder


# Пути по умолчанию модулей конвейера, указывающие в РАБОЧУЮ КОПИЮ репозитория
# (`data/...`, `wiki`). Любой тест, забывший передать соответствующий флаг,
# читает боевой корпус вместо своей fixture — и это не теория: до этого файла
# `test_run._args` не передавал `--site-root`/`--site-manifest`, поэтому три
# теста `test_run.py` молча разбирали 177 живых страниц FAQ и 1078 страниц
# блогов из `data/raw/site/` (17,0 с + 8,9 с + 8,5 с из 36 с всего набора —
# ровно те, что стояли в топе `--durations`). Тест при этом зелёный, но
# проверяет он не то, что написано, и на чистом чекауте без `data/` ведёт
# себя иначе.
_SANDBOXED_DEFAULTS = (
    ("pipeline.run", "DEFAULT_PAGES"),
    ("pipeline.run", "DEFAULT_MANIFEST"),
    ("pipeline.run", "DEFAULT_DB"),
    ("pipeline.run", "DEFAULT_CSV"),
    ("pipeline.run", "DEFAULT_WIKI"),
    ("pipeline.run", "DEFAULT_ASSETS_MANIFEST"),
    ("pipeline.run", "DEFAULT_ASSETS_ROOT"),
    ("pipeline.run", "DEFAULT_SITE_ROOT"),
    ("pipeline.run", "DEFAULT_SITE_MANIFEST"),
    ("pipeline.mirror", "DEFAULT_ASSETS_ROOT"),
    ("pipeline.mirror_faq", "DEFAULT_ASSETS_MANIFEST"),
    ("pipeline.mirror_faq", "DEFAULT_ASSETS_ROOT"),
    ("pipeline.mirror_blog", "DEFAULT_ASSETS_MANIFEST"),
    ("pipeline.mirror_blog", "DEFAULT_ASSETS_ROOT"),
)


@pytest.fixture(autouse=True)
def sandbox_default_paths(request, monkeypatch, tmp_path_factory):
    """Пути по умолчанию уводятся в НЕсуществующий каталог под tmp.

    Смысл тот же, что у `no_network`: забытый флаг должен давать пустой
    результат (и падающий тест), а не молча подхватывать боевые данные из
    рабочей копии. Тесту, которому боевой корпус действительно нужен,
    ставится маркер `@pytest.mark.real_data` — сегодня таких нет.
    """
    if request.node.get_closest_marker("real_data"):
        return
    import importlib
    box = tmp_path_factory.mktemp("sandbox-defaults")
    for module_name, attr in _SANDBOXED_DEFAULTS:
        module = importlib.import_module(module_name)
        current = getattr(module, attr)
        monkeypatch.setattr(module, attr, box / ("нет-" + attr.lower()) / Path(current).name)
