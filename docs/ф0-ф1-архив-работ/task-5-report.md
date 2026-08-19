# Отчёт по задаче 5: загрузка в базу с дедупом постов

## Что сделано

1. Создан `tests/test_ingest.py` — оба теста из брифа дословно (Шаг 1).
2. Проверено, что тесты падают: `No module named 'pipeline.ingest'` (Шаг 2).
3. Реализован `pipeline/ingest.py` — `upsert_post`, `ingest_all`, по коду из брифа
   (Шаг 3), с минимальными изменениями:
   - regex вынесен в модульную константу `_PAGE_RE`;
   - добавлен docstring с обоснованием, почему `page_no` для `message_*` всегда `1`
     и почему `mid` берётся из `Post.mid`, а не из имени файла (см. «Факты о
     корпусе» ниже);
   - логика дедупа, апсерта тем (`ON CONFLICT ... pages_expected=max(...)`) и
     классификация вложений (`local`/`external_image`) — как в брифе, без
     изменений.
4. Тесты зелёные (Шаг 4).
5. Полный прогон по всему корпусу (Шаг 5), см. цифры ниже.
6. Коммит (Шаг 6).

## Вывод тестов

```
$ cd ~/code/Python/subaru-faq && .venv/bin/python -m pytest tests/test_ingest.py -v
tests/test_ingest.py::test_ingest_counts_and_dedups PASSED               [ 50%]
tests/test_ingest.py::test_longer_text_wins_on_conflict PASSED           [100%]
2 passed in 0.09s
```

Полный прогон всего набора тестов проекта (ничего не сломано):

```
$ cd ~/code/Python/subaru-faq && .venv/bin/python -m pytest -v
23 passed in 0.20s
```

## Полный прогон по корпусу

Воспроизводимая команда:

```bash
cd ~/code/Python/subaru-faq
rm -f data/forum.sqlite data/forum.sqlite-wal data/forum.sqlite-shm
.venv/bin/python -c "
from pathlib import Path
from pipeline import db, ingest
conn = db.connect(Path('data/forum.sqlite')); db.init_schema(conn)
stats = ingest.ingest_all(Path('data/raw/archive/pages'), Path('data/raw/archive/manifest.jsonl'), conn)
print('STATS', stats)
print('threads_rows', conn.execute('SELECT COUNT(*) FROM threads').fetchone()[0])
print('posts_rows', conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0])
print('pages_rows', conn.execute('SELECT COUNT(*) FROM pages').fetchone()[0])
print('attachments_rows', conn.execute('SELECT COUNT(*) FROM attachments').fetchone()[0])
print('distinct_mid_in_posts', conn.execute('SELECT COUNT(DISTINCT mid) FROM posts').fetchone()[0])
print('threads_without_posts', conn.execute('SELECT COUNT(*) FROM threads t WHERE NOT EXISTS (SELECT 1 FROM posts p WHERE p.tid=t.tid)').fetchone()[0])
"
```

Вывод (счётчики `ingest_all`, потом контрольные запросы к базе):

```
STATS {'threads': 4915, 'posts': 60982, 'pages': 5699, 'attachments': 29376}
threads_rows 4726
posts_rows 48689
pages_rows 5699
attachments_rows 29376
distinct_mid_in_posts 48689
threads_without_posts 2829
```

Расшифровка:

| Метрика | Значение | Комментарий |
|---|---|---|
| `stats["threads"]` | 4915 | счётчик обработанных строк оглавлений (одна тема повторяется на нескольких `list_*.html`, апсерт схлопывает в уникальные `tid`) |
| строк в `threads` | **4726** | совпадает с известным числом уникальных тем из оглавлений |
| `stats["posts"]` | 60982 | счётчик обработанных постов ДО дедупа (каждое вхождение поста на любой странице) |
| строк в `posts` | **48689** | после дедупа по `mid` — совпадает с известным числом уникальных `mid` **точно** |
| постов отброшено дедупом | **12293** (60982 − 48689) | инстансы поста, схлопнутые в уже существующую строку (короче — пропущены, длиннее — перезаписали) |
| строк в `pages` | **5699** | см. «Почему pages не 5937» ниже |
| строк в `attachments` | **29376** | 18653 `local`, 10723 `external_image` (классификация по эвристике из брифа: `local`, если URL содержит `subaru-faq` или начинается с `/`) |
| тем без единого поста | **2829** | больше, чем ожидавшиеся «примерно 1200» — разобрано ниже |

### Почему `pages` = 5699, а не 5937

Ожидание в брифе (`pages` = 5937) предполагало, что каждый файл в `data/raw/archive/pages/`
— это страница темы. Это не так: в каталоге вперемешку лежат файлы четырёх видов:

| Вид | Количество | Куда идёт |
|---|---|---|
| `read_<fid>_<tid>_<page>.html` | 3400 | обрабатывается в цикле страниц → `pages`/`posts` |
| `message_<fid>_<tid>_<mid>.html` | 2299 | туда же |
| `list_<fid>_<page>.html` | 235 | обрабатывается отдельным циклом → `threads`, в счётчик `pages` не входит |
| `index_1.html` | 1 | не подходит ни под один паттерн, парсера для него нет — пропускается |
| файлы со сломанным/аномальным именем | 2 | пропускаются (см. ниже) |

3400 + 2299 = 5699 — ровно столько, сколько записалось в `pages`. Итог сходится, брифовское
«ожидается 5937» было не совсем точным (не учитывало `list_*`/`index_*` в том же каталоге).

### Дедуп по `mid`: сходится ли с известными 48689?

Да, **точно**: `distinct_mid_in_posts` = 48689 = `posts_rows` (PRIMARY KEY на `mid`
гарантирует отсутствие дублей физически). Это совпадает с фактом, установленным
предыдущими задачами («всего постов 60996, уникальных mid — 48689»).

Разница между 60996 (известное общее число постов в корпусе) и 60982
(`stats["posts"]`, число обработанных постов в этом прогоне) — **14** постов.
Она полностью объясняется двумя пропущенными файлами (см. следующий раздел):
`message_7_68277_unread_mid.html` (13 постов) и `read_23_23771<br_1.html` (1 пост).
Оба содержательно дублируют корректно поименованные файлы для тех же тем — потери
контента нет, проверено побайтовым сравнением множества `id="messageNNN"` (см. ниже).

## Файл со сломанным именем `read_23_23771<br_1.html`

**Решение: пропущен** (регексп `_PAGE_RE` не матчит `<br` внутри сегмента TID,
`if not m: continue`).

**Почему это безопасно** — проверено эмпирически, а не предположено:

```bash
LC_ALL=C grep -o 'id="message[0-9]*"' --binary-files=text "data/raw/archive/pages/read_23_23771<br_1.html" | sort -u > /tmp/d.txt
LC_ALL=C grep -o 'id="message[0-9]*"' --binary-files=text "data/raw/archive/pages/read_23_23771_1.html" | sort -u > /tmp/e.txt
diff /tmp/d.txt /tmp/e.txt   # пусто — множества id идентичны (1 пост)
```

Множество `id="messageNNN"` в сломанном файле совпадает 1:1 с корректно
поименованным `read_23_23771_1.html`, который обход каталога находит и разбирает
штатно. Пропуск сломанного файла не теряет ни одного поста.

## Обнаружен ещё один аномально поименованный файл (не был в списке фактов брифа)

`message_7_68277_unread_mid.html` — третий сегмент имени не число (`unread_mid`
вместо MID), тоже не матчится `_PAGE_RE` и тоже пропускается. Проверено так же
эмпирически:

```bash
LC_ALL=C grep -o 'id="message[0-9]*"' --binary-files=text data/raw/archive/pages/message_7_68277_412539.html | sort -u > /tmp/a.txt
LC_ALL=C grep -o 'id="message[0-9]*"' --binary-files=text data/raw/archive/pages/message_7_68277_unread_mid.html | sort -u > /tmp/b.txt
diff /tmp/a.txt /tmp/b.txt   # пусто
LC_ALL=C grep -o 'id="message[0-9]*"' --binary-files=text data/raw/archive/pages/message_7_68277_1.html | sort -u > /tmp/c.txt
diff /tmp/a.txt /tmp/c.txt   # пусто
```

Для темы `fid=7/tid=68277` в архиве три файла (`message_7_68277_412539.html`,
`message_7_68277_1.html`, `message_7_68277_unread_mid.html`), все три содержат
идентичный набор из 13 `id="messageNNN"` — чистый дубль (судя по всему, `unread_mid`
— обрывок query-параметра `?unread_mid=...`, который скрейпер вставил в имя файла
вместо MID). Решение то же, что и для `<br>`-файла: пропустить, контент не теряется.

## Проверка: 37 файлов `message_*` с номером страницы вместо MID в последнем сегменте

Не создаёт проблемы для реализации: `page_no` для `kind == "message"` жёстко
зафиксирован в `1` (весь `message_*`-файл — плоский снимок темы, а не одна страница
из нескольких), последний сегмент имени файла (`tail`) для message-веток вообще не
используется. Настоящий `mid` каждого поста берётся из `id="messageNNN"` внутри
самой таблицы (`Post.mid` из `parse_thread`), не из имени файла. Отдельно
проверять эти 37 файлов поштучно не потребовалось — код структурно не может
спутать номер страницы с `mid`.

## Конфликтующие по `fid` темы (last-write-wins)

Обнаружено **ровно 12** тем, у которых `fid` отличается между разными
`list_*.html` — совпадает с фактом из брифа. Список (tid, старый fid → новый fid,
файл-источник новой версии), в порядке `sorted()`-обхода (тот же порядок,
что использует `ingest_all`):

| tid | fid было | из файла | fid стало | из файла |
|---|---|---|---|---|
| 38247 | 18 | list_18_36.html | 21 | list_21_5.html |
| 37092 | 14 | list_14_44.html | 3 | list_3_350.html |
| 37300 | 14 | list_14_44.html | 3 | list_3_352.html |
| 41881 | 17 | list_17_1.html | 3 | list_3_374.html |
| 29690 | 18 | list_18_1.html | 4 | list_4_399.html |
| 36152 | 3 | list_3_353.html | 5 | list_5_1.html |
| 37162 | 21 | list_21_5.html | 7 | list_7_37.html |
| 34120 | 21 | list_21_5.html | 7 | list_7_37.html |
| 37414 | 21 | list_21_5.html | 7 | list_7_37.html |
| 37843 | 21 | list_21_5.html | 7 | list_7_40.html |
| 42168 | 28 | list_28_48.html | 7 | list_7_66.html |
| 32701 | 14 | list_14_38.html | 8 | list_8_4.html |

Проверено по факту: в итоговой базе `fid` для каждой из этих тем равен
последнему значению по порядку обхода (например, tid=29690 → `fid=4`,
tid=38247 → `fid=21`) — `ON CONFLICT DO UPDATE SET fid=excluded.fid`
работает как задумано, «последняя запись побеждает».

## Неожиданная находка: 1612 тем с постами не встречаются ни в одном оглавлении

Бриф ожидал: 4726 тем из оглавлений − 3519 тем с `read_*`/`message_*`-страницами
≈ 1207 тем «только в оглавлениях, без единой страницы с постами». Фактически
`threads_without_posts` = **2829**, что намного больше 1207. Разобрался, почему:

```
distinct tid в posts:                         3509   (= 3519 minus 10 «пустых» message-страниц, см. ниже)
  из них есть в threads (пересечение):        1897
  из них НЕТ в threads:                       1612   ← темы существуют по факту постов, но не в оглавлениях
threads_rows (из оглавлений):                 4726
  из них есть посты:                          1897
  из них без постов:                          2829   ← 4726 − 1897, это и есть threads_without_posts
```

То есть множества «темы из оглавлений» (4726) и «темы со страницами постов» (3509)
пересекаются лишь на 1897, а не почти полностью, как подразумевала оценка
«≈1200». Проверил, что это не баг извлечения `tid` из имени файла: свежесобранная
tid для файлов `message_*` — третий сегмент имени, `TID` из `manifest.jsonl`
подтверждает это дословно, например:

```
message_3_66_567.html → url: ...PAGE_NAME=message&FID=3&TID=66&MID=567...
```

`tid=66` из имени файла точно соответствует `TID=66` в URL — извлечение верное.
Значит для ~1612 тем архив содержит страницы с постами, но не содержит ни одной
строки в собранных оглавлениях (крауler не дошёл до старой/глубокой страницы
листинга этого раздела, либо тема к моменту снятия оглавления уже пропала из
списка). Это дыра архива того же типа, что и «темы только в оглавлениях», только
в обратную сторону — не моя ошибка и не ошибка парсера, факт корпуса. Задача 5 не
требует чинить это (`sections`/полнота листингов — вне scope), фиксирую для
следующих задач (проверка покрытия).

Дополнительно: 8 из 3519 `message_*`-страниц (`fid_tid`: 18/96388, 22/92460,
25/95763, 26/93386, 3/93533, 4/58261, 4/93532, 5/93523) — единственный файл для
своей темы и дают 0 постов (в сохранённом HTML нет `forum-post-text`, только
JS/реклама — сбой снятия снимка, MID=0 в имени файла). Ещё 2 «нулевых» файла
(4/32503, 5/82516) на самом деле дублируют другие, содержательные файлы той же
темы — контент не теряется. Итого реальных «пустых» тем из-за сбоя снятия
снимка — 8, они уже включены в `threads_without_posts`, если тема также
присутствует в оглавлениях, либо просто не создают строк, если нет.

## Хэши коммитов

```
59665e2 feat(ingest): загрузка страниц в SQLite с дедупом постов по mid
```

Файлы коммита: `pipeline/ingest.py` + `tests/test_ingest.py` (2 файла, 144 строки).
Родительский коммит: `caf521e` (готовые парсеры, как передано в задаче).

## Сомнения / что стоит перепроверить в следующих задачах

1. **Оценка «≈1200 тем только в оглавлениях» из брифа не подтвердилась** — реальное
   число тем без постов 2829, из-за 1612 тем, которые есть в page-файлах, но
   отсутствуют в собранных оглавлениях (см. раздел выше). Это не блокирует задачу 5,
   но задача 6 (проверка покрытия) должна знать про эту асимметрию, а не только
   про «темы-только-в-оглавлениях».
2. Классификация `local`/`external_image` в `attachments` — эвристика из брифа
   (`"subaru-faq" in url or url.startswith("/")`) взята дословно, не проверял её
   корректность против реальных URL картинок (это, по-видимому, забота задачи про
   зеркало/картинки, не пятой задачи) — 18653 `local` / 10723 `external_image`.
3. Не проверял `manifest.jsonl` на «мёртвые» записи (файл есть в манифесте, но
   отсутствует на диске, или наоборот) — не требовалось интерфейсом задачи, но если
   в будущем понадобится валидация происхождения (`pages.url`/`snapshot_ts`), это
   не покрыто.
4. `data/raw/archive/broken/read_18_41771_1.html` (1 файл вне `pages_dir`) в этот
   прогон не входил — по команде из брифа `ingest_all` вызывается только на
   `data/raw/archive/pages`, `broken/` не передавался. Явно не входило в scope
   задачи, оставляю как есть.

---

## Правка по замечанию ревью: сироты-посты для тем без оглавления

Тимлид указал на несущий дефект: `threads` заполнялся только из `list_*.html`,
поэтому 1612 тем, у которых есть страницы с постами, но нет строки ни в одном
оглавлении, не попадали в `threads` вовсе — их посты оставались сиротами
(`tid`, которого нет в `threads`), и задача 7 (обход `SELECT tid FROM threads`)
потеряла бы их контент из зеркала целиком.

### TDD

1. Написал два падающих теста в `tests/test_ingest.py`:
   - `test_orphan_thread_gets_created_and_posts_not_orphaned` — страница темы
     без единого `list_*.html` в фикстурах; после `ingest_all` в `threads` должна
     быть строка для её `tid`, `replies_expected IS NULL`, и
     `SELECT COUNT(*) FROM posts p LEFT JOIN threads t USING(tid) WHERE t.tid IS NULL`
     = 0.
   - `test_listing_data_wins_over_page_fallback_regardless_of_order` — прямой
     вызов новых функций `upsert_thread_from_listing`/`ensure_thread_from_page`
     в обоих порядках (фолбэк→оглавление и оглавление→фолбэк): в обоих случаях
     в базе должны остаться данные оглавления, а не со страницы темы.
2. Убедился, что оба падают на дореформенном коде:
   ```
   AssertionError: тема без оглавления должна получить строку в threads
   AttributeError: module 'pipeline.ingest' has no attribute 'ensure_thread_from_page'
   ```
3. Реализация — две новые функции в `pipeline/ingest.py`:
   - `upsert_thread_from_listing(conn, t)` — вынесенный без изменений прежний
     инлайн-SQL апсерта темы из оглавления (авторитетный источник, перезаписывает
     всё, включая ранее созданный фолбэк).
   - `ensure_thread_from_page(conn, *, tid, fid, title)` — `INSERT OR IGNORE`:
     если строки для `tid` ещё нет, создаёт её с `fid`/`title` со страницы, но
     `author=NULL, started_at=NULL, replies_expected=NULL, views=NULL,
     pages_expected=NULL` — **NULL, а не 0**: NULL значит «сколько постов должно
     быть — неизвестно, темы нет в оглавлении», ноль соврал бы, что тема пустая.
     Если строка уже есть (из оглавления или из более ранней по обходу
     страницы-фолбэка той же темы) — не трогает её.
   - В `ingest_all`: `ensure_thread_from_page` вызывается в цикле по страницам
     **только когда `page.posts` не пуст**. Важная находка по ходу правки: часть
     страниц с постами `== 0` (см. «Проверка: 37 файлов…» и раздел про 8 zero-post
     `message_*`-файлов выше) на самом деле оказались **спам-темами** с MID=0
     в имени файла и мусорными заголовками (`"adidas Tubular Radial comes in a
     Tonal Black theme"`, `"FanPost Friday: Spot upon your GM hat…"` и т.п.) —
     без этой проверки они превратились бы в мусорные строки `threads` с
     спам-заголовками, которые задача 7 протащила бы в зеркало базы знаний как
     пустые статьи со спам-названиями. Из 8 таких тем ровно одна (`МОЗГИ
     двигателе (перегорел резистор и предохранитель)`, fid=4/tid=58261) выглядит
     как настоящий, но не захваченный контент — тоже корректно не создаёт
     строку `threads` (нет постов → нечего адресовать), это не потеря по вине
     кода, а дыра самого архива.
   - `ingest_all` также получил счётчик `stats["skipped_files"]` (расширение
     интерфейса `dict[str, int]`, обратной совместимости не ломает — существующие
     тесты не проверяют точный набор ключей).
4. Тесты зелёные:
   ```
   $ .venv/bin/python -m pytest -v
   25 passed in 0.32s
   ```

### Коммит правки

```
5e091c1 fix(ingest): заводить threads для тем без оглавления, чтобы посты не сиротели
```
Родитель: `59665e2` (первичная реализация задачи 5).

### Полный прогон после правки

Та же воспроизводимая команда, что и выше (Шаг 5 брифа), плюс диагностические
запросы:

```bash
cd ~/code/Python/subaru-faq
rm -f data/forum.sqlite data/forum.sqlite-wal data/forum.sqlite-shm
.venv/bin/python -c "
from pathlib import Path
from pipeline import db, ingest
conn = db.connect(Path('data/forum.sqlite')); db.init_schema(conn)
stats = ingest.ingest_all(Path('data/raw/archive/pages'), Path('data/raw/archive/manifest.jsonl'), conn)
print('STATS', stats)
print('threads_rows', conn.execute('SELECT COUNT(*) FROM threads').fetchone()[0])
print('orphan_posts', conn.execute('SELECT COUNT(*) FROM posts p LEFT JOIN threads t USING(tid) WHERE t.tid IS NULL').fetchone()[0])
print('threads_replies_expected_null (создано из страниц)', conn.execute('SELECT COUNT(*) FROM threads WHERE replies_expected IS NULL').fetchone()[0])
print('threads_replies_expected_not_null (из оглавлений)', conn.execute('SELECT COUNT(*) FROM threads WHERE replies_expected IS NOT NULL').fetchone()[0])
print('threads_with_posts', conn.execute('SELECT COUNT(*) FROM threads t WHERE EXISTS (SELECT 1 FROM posts p WHERE p.tid=t.tid)').fetchone()[0])
print('threads_without_posts', conn.execute('SELECT COUNT(*) FROM threads t WHERE NOT EXISTS (SELECT 1 FROM posts p WHERE p.tid=t.tid)').fetchone()[0])
print('threads_in_listing_and_have_posts', conn.execute('''
  SELECT COUNT(*) FROM threads t
  WHERE t.replies_expected IS NOT NULL
    AND EXISTS (SELECT 1 FROM posts p WHERE p.tid = t.tid)
''').fetchone()[0])
"
```

Вывод:

```
STATS {'threads': 4915, 'posts': 60982, 'pages': 5699, 'attachments': 29376, 'skipped_files': 2}
threads_rows 6338
orphan_posts 0
threads_replies_expected_null (создано из страниц) 1612
threads_replies_expected_not_null (из оглавлений) 4726
threads_with_posts 3509
threads_without_posts 2829
threads_in_listing_and_have_posts 1897
```

Ответы на пункты 4–5 из ревью:

| Вопрос | Ответ |
|---|---|
| Строк в `threads` после правки | **6338** = 4726 (из оглавлений) + 1612 (созданы фолбэком из страниц) |
| Из них создано из страниц (без оглавления) | **1612** — ровно совпадает с найденным ранее числом тем «есть посты, нет в оглавлении» |
| Сирот-постов осталось | **0** ✓ (`posts LEFT JOIN threads` → 0 строк без `tid`) |
| Тем с `replies_expected IS NULL` | **1612** — совпадает с «создано из страниц»: только фолбэк-строки получают NULL, у всех строк из оглавлений `replies_expected` всегда число (0 и больше) |
| Тем, у которых есть и оглавление, и хотя бы один пост (полноценная проверка полноты по счётчику ответов в задаче 6 возможна только для них) | **1897** |

`posts_rows`/`distinct_mid_in_posts`/`pages_rows`/`attachments_rows` не
изменились (48689 / 48689 / 5699 / 29376) — правка не трогает посты и страницы,
только заполнение `threads`. `threads_without_posts` тоже не изменилось (2829) —
ожидаемо: фолбэк создаёт строку только когда у страницы есть посты, так что
множество «тем без единого поста» (все они из оглавлений) правкой не
затронуто.

### Пропущенные файлы — полный список с причиной (`stats["skipped_files"]` = 2)

Проверил счётчиком в самом коде (`stats["skipped_files"]`, считает только файлы
с префиксом `read_`/`message_`, не совпавшие с `_PAGE_RE`; `list_*.html` и
`index_*.html` — не пропуск, а отдельная, штатно обрабатываемая категория) —
на реальном корпусе выходит ровно 2, других аномалий с такими префиксами нет:

| Файл | Причина пропуска | Проверка отсутствия потерь |
|---|---|---|
| `read_23_23771<br_1.html` | `<br` вклинился в сегмент TID имени файла, `_PAGE_RE` не матчит | `id="messageNNN"` совпадает 1:1 с `read_23_23771_1.html` (тот же 1 пост) — дубль, ничего не теряется |
| `message_7_68277_unread_mid.html` | последний сегмент — текст `unread_mid` (обрывок query-параметра), а не MID | `id="messageNNN"` совпадает 1:1 с `message_7_68277_412539.html` и `message_7_68277_1.html` (те же 13 постов) — дубль, ничего не теряется |

Оба случая — осознанный, проверенный эмпирически пропуск, а не случайная потеря
данных.

---

## Правка 2 по замечанию ревью: классификация `local`/`external_image`

Ревью нашло измеримый дефект в эвристике из брифа:

```python
kind_a = "local" if "subaru-faq" in url or url.startswith("/") else "external_image"
```

Она не распознавала относительный путь **без** ведущего слэша —
`images/smiley_icons/icon_smile.gif` (смайлы форума) уходили в
`external_image`, хотя `/bitrix/images/smiley_icons/icon_smile.gif` (та же
картинка с ведущим слэшем) классифицировалась бы как `local`. Задача 7 решает
по `kind`, вставлять ли локальный файл или коллаут «не сохранилось», а задача
добора внешних картинок пыталась бы качать эти 2110+ смайлов из Wayback как
внешние — их там нет и быть не может, это ассеты самого форума.

### TDD

Тест `test_classify_attachment_relative_path_without_leading_slash_is_local`
проверяет напрямую новую функцию `ingest._classify_attachment`:
- `images/smiley_icons/icon_smile.gif` → `local` (было: `external_image`)
- `/bitrix/images/smiley_icons/icon_smile.gif` → `local` (не изменилось)
- `http://s017.radikal.ru/i430/x.jpg` → `external_image` (не изменилось)
- `//i57.fastpic.ru/big/x.jpg` (протокол-относительный) → `external_image`
  (граничный случай, которого раньше не было в тестах вовсе)

Упал на дореформенном коде: `AttributeError: module 'pipeline.ingest' has no
attribute '_classify_attachment'` — функции ещё не существовало.

### Реализация

```python
def _classify_attachment(url: str) -> str:
    netloc = urlparse(url).netloc
    if not netloc or "subaru-faq" in netloc:
        return "local"
    return "external_image"
```

Смысл: локальный — это любой адрес без собственного хоста (`urlparse(url).netloc`
пуст — относительный путь, с ведущим слэшем или без) плюс адреса самого форума;
внешний — `http(s)://` или протокол-относительный (`//host/...`) адрес любого
другого хоста. `urlparse("//host/x").netloc` возвращает хост и без явной схемы,
поэтому оба граничных случая (`http://`/`https://` и `//host/...`) проверяются
одним и тем же полем `netloc`, без отдельной ветки под протокол-относительные
адреса.

Тесты зелёные:
```
$ .venv/bin/python -m pytest -v
26 passed in 0.25s
```

### Коммит

```
d07ad07 fix(ingest): классификация local/external_image учитывает относительный путь без ведущего слэша
```
Родитель: `5e091c1`.

### Числа после пересборки

```bash
cd ~/code/Python/subaru-faq
rm -f data/forum.sqlite data/forum.sqlite-wal data/forum.sqlite-shm
.venv/bin/python -c "
from pathlib import Path
from pipeline import db, ingest
conn = db.connect(Path('data/forum.sqlite')); db.init_schema(conn)
stats = ingest.ingest_all(Path('data/raw/archive/pages'), Path('data/raw/archive/manifest.jsonl'), conn)
print('STATS', stats)
print('attachments by kind:', list(conn.execute('SELECT kind, COUNT(*) FROM attachments GROUP BY kind')))
"
```

```
STATS {'threads': 4915, 'posts': 60982, 'pages': 5699, 'attachments': 29376, 'skipped_files': 2}
attachments by kind: [('external_image', 8612), ('local', 20764)]
```

| | до правки | после правки | сменили класс |
|---|---|---|---|
| `local` | 18653 | **20764** | +2111 |
| `external_image` | 10723 | **8612** | −2111 |

2111 записей перешли из `external_image` в `local` (все — относительные пути
вида `images/...` без ведущего слэша, преимущественно смайлы
`images/smiley_icons/icon_*.gif`). В обратную сторону изменений нет — ошибка
была строго односторонней, как и предупреждал ревьюер (называл оценку «2110»,
фактически 2111 — разница в одну запись не критична, оценка была на глаз).

### Осмотр выборки нового `external_image`

Взял 30 случайных URL из `external_image` после правки
(`ORDER BY RANDOM() LIMIT 30`) — все оказались настоящими внешними хостами
(`radikal.ru`, `vk.me`/`vkontakte.ru`, `imageshack.us`, `img-fotki.yandex.ru`,
`content.foto.mail.ru`, `photofile.name`, `photo.qip.ru`, `avito.st`,
`piccy.info`, `kepa.ru`, `ontuning.ru`, `opera-ac.clan.su`,
`xn----dtbbfrdosbp5ae0n.xn--p1ai` — punycode-домен) — ни одного относительного
пути третьего вида не попалось.

### Мусорные URL (`<a href=` и аналогичные)

Поискал по всей базе `url LIKE '%<%' OR url LIKE '%href%'` — нашлось **ровно 2**
записи, не сотни:

| mid | kind | url |
|---|---|---|
| 162687 | local | `<a href=` |
| 155571 | external_image | `http://clip2net.com/page/m0/548204"><img src="http://clip2net.com/clip/m0/1232443624-clip-17kb.jpg` |

Первая (162687) — та, что уже отметил ревьюер: артефакт двойного
экранирования на исходной странице, приходит из `html_text.images()`, не
трогаю по договорённости. Вторая (155571) — похожий артефакт (два `<img>`
внутри одного href слиплись в один URL при экранировании), классифицирован
как `external_image` через `netloc="clip2net.com"` — корректно, несмотря на
мусор в самой строке. Единицы, не десятки и не сотни — фиксирую по
договорённости, не чиню.
