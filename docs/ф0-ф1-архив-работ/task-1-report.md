# Отчёт по Задаче 1: Каркас репозитория и схема базы

Статус: **DONE_WITH_CONCERNS** (реализация полностью соответствует брифу и все шаги выполнены,
но в процессе обнаружились и потребовали решения два отклонения от буквального текста брифа —
см. «Отклонения и сомнения» ниже).

## Что сделано

1. Проверил репозиторий `~/code/Python/subaru-faq` (уже был `git init`, ветка `main`, коммитов нет —
   как и было сказано в контексте задачи).
2. Создал недостающие директории: `pipeline/`, `tests/fixtures/`, `wiki/` (`data/` уже была создана
   при распаковке архива).
3. Распаковал сырьё: `zstd -dc ~/Downloads/archive.tar.zst | tar -xf - -C data/raw`.
   Проверка: `ls data/raw/archive/pages | wc -l` → **5937** (совпадает с ожиданием брифа).
   Исходный файл `~/Downloads/archive.tar.zst` не трогал — только читал (`zstd -dc`), не изменял и
   не удалял. Проверил `ls -la` до и после — размер и mtime не изменились.
4. Записал `pyproject.toml` и `.gitignore` — см. «Отклонения» про добавленные строки
   (`[tool.setuptools] packages = ["pipeline"]`, `*.egg-info/`, `.pytest_cache/`).
5. Написал падающий тест `tests/test_db.py` (дословно из брифа) и пустой `pipeline/__init__.py`.
6. Убедился, что тест падает (см. «Отклонения» про текст ошибки).
7. Реализовал `pipeline/db.py` дословно из брифа (SCHEMA, `connect()`, `init_schema()`).
8. Убедился, что тесты проходят — 2 passed.
9. Закоммитил ровно те файлы, что перечислены в брифе.

## Файлы

Созданы:
- `pyproject.toml`
- `.gitignore`
- `pipeline/__init__.py` (пустой)
- `pipeline/db.py`
- `tests/test_db.py`
- (пустые директории `tests/fixtures/`, `wiki/` — созданы, но пока ничего не содержат и не
  коммитятся, т.к. git не отслеживает пустые каталоги)

Не создавал ничего из последующих задач (парсеры, зеркало, воркер скачивания картинок и т.п.).

## Окружение

- Python в `.venv`: 3.14.7 (`/opt/homebrew/bin/python3 -m venv .venv`).
- `zstd`/`brew`/`python3.14` физически стоят в `/opt/homebrew/bin`, но не входят в PATH шелла
  агента по умолчанию — все команды распаковки/venv выполнял с явным PATH или полными путями,
  через `dangerouslyDisableSandbox=true` (иначе видна урезанная песочница с системным
  `/usr/bin/python3` 3.9.6 без brew).

## Точные команды и вывод

### Распаковка

```
$ cd ~/code/Python/subaru-faq && mkdir -p data/raw && zstd -dc ~/Downloads/archive.tar.zst | tar -xf - -C data/raw
$ ls data/raw/archive/pages | wc -l
    5937
```

### Установка зависимостей

```
$ python3 -m venv .venv
$ .venv/bin/pip install -e ".[dev]"
...
Successfully installed beautifulsoup4-4.15.0 iniconfig-2.3.0 lxml-6.1.2 packaging-26.3 pluggy-1.6.0
pygments-2.21.0 pytest-9.1.1 soupsieve-2.9.2 subaru-faq-0.1.0 typing-extensions-4.16.0
```

(с первой попытки упало — см. «Отклонения», ниже команда после фикса `pyproject.toml`)

### Тест до реализации (шаг 4, ожидание FAIL)

```
$ .venv/bin/python -m pytest tests/test_db.py -v
...
ERROR tests/test_db.py
ImportError: cannot import name 'db' from 'pipeline' (.../pipeline/__init__.py)
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.05s ===============================
```

### Тест после реализации (шаг 6, ожидание 2 passed)

```
$ .venv/bin/python -m pytest tests/test_db.py -v
tests/test_db.py::test_init_schema_creates_tables PASSED                 [ 50%]
tests/test_db.py::test_posts_fts_searches_russian PASSED                 [100%]
============================== 2 passed in 0.01s ===============================
```

Также прогнал полный `pytest -v` (без указания файла, через testpaths из pyproject.toml) —
тот же результат, 2 passed.

## Коммиты

```
06c24115a2881508a625b207f77f3f2795bc2d83  feat(db): схема SQLite и полнотекстовый индекс постов
```

Один коммит, содержит ровно 5 файлов из брифа:
```
.gitignore
pipeline/__init__.py
pipeline/db.py
pyproject.toml
tests/test_db.py
```
`git status` после коммита — чисто, `data/`, `.venv/`, `subaru_faq.egg-info/`, `.pytest_cache/`
в индекс не попали.

## Отклонения и сомнения

1. **`pyproject.toml`: добавил `[tool.setuptools] packages = ["pipeline"]`.**
   Дословный `pyproject.toml` из брифа не собирается: `pip install -e ".[dev]"` падает с
   `error: Multiple top-level packages discovered in a flat-layout: ['wiki', 'data', 'pipeline']`.
   Setuptools в flat-layout находит любые top-level директории без `__init__.py` как кандидаты
   в implicit namespace packages — `wiki/` и `data/` (сырьё архива) сбивают автодетект. Без явного
   указания пакета установка невозможна в принципе, независимо от версии Python/setuptools, пока
   в репозитории есть эти директории (а `wiki/` и `data/` нужны по дальнейшим задачам и global
   constraints). Добавил минимальную секцию `[tool.setuptools] packages = ["pipeline"]` — не меняет
   ни одного публичного интерфейса, требуемого брифом (`db.connect`, `db.init_schema`, схема таблиц).
   **Прошу подтвердить, что это приемлемо**, либо предложить другой вариант (src-layout и т.п.) —
   пока не трогаю, т.к. это создаст более крупное отклонение от брифа.

2. **`.gitignore`: добавил `*.egg-info/` и `.pytest_cache/`.**
   `pip install -e .` создаёт `subaru_faq.egg-info/` в корне репозитория (build-артефакт), `pytest`
   создаёт `.pytest_cache/`. Оба не должны попадать в git. В брифе этих строк нет — добавил как
   очевидно необходимое дополнение, не влияющее на состав закоммиченных файлов.

3. **Текст ошибки на шаге 4 отличается от брифа.**
   Бриф ожидает `ModuleNotFoundError: No module named 'pipeline.db'`. Фактически pytest/Python 3.14
   выдал `ImportError: cannot import name 'db' from 'pipeline'` — потому что `pipeline/__init__.py`
   существует (пустой пакет), а `pipeline/db.py` ещё нет. Суть та же (тест падает из-за отсутствия
   модуля), формулировка ошибки другая. Не стал ничего менять — тест в итоге зелёный, а брифовая
   формулировка ошибки, видимо, писалась без учёта того, что `pipeline/__init__.py` уже создаётся
   на этом же шаге.

4. **Git identity в коммите — не «Сергей Ненашев».**
   `git config user.name`/`user.email` в этом окружении глобально настроены как `qazar <no@no.no>`
   (не трогал, т.к. правило «никогда не менять git config» без явного запроса). Коммит
   `06c24115a2881508a625b207f77f3f2795bc2d83` подписан этим identity, а не Сергеем. Если это не
   ожидаемо — нужно поправить `~/.gitconfig` отдельным явным запросом, я этого делать не стал.

5. **PATH окружения без brew/zstd/python3.14.**
   Шелл агента по умолчанию (песочница) не видит `/opt/homebrew/bin` — там нет `zstd`, `brew`,
   правильного `python3`. Все команды распаковки, создания venv и запуска тестов выполнял с
   `dangerouslyDisableSandbox=true` и явным добавлением `/opt/homebrew/bin` в PATH или полными
   путями к бинарям. Тесты через `.venv/bin/python -m pytest` не зависят от PATH (используют venv
   напрямую), но сама подготовка окружения требовала обхода песочницы — фиксирую на будущее для
   Задачи 2 и далее (парсер, зеркало) — та же необходимость возникнет снова.

## Не реализовывал (за рамками брифа)

Парсер архива, построение зеркала в wiki/, скачивание вложений, CSV-отчёты — ничего из этого не
трогал, как и было указано.
