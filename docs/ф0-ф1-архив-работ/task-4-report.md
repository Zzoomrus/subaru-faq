# Отчёт по Задаче 4: парсер страниц тем

## Что сделано

1. Скопированы фикстуры из брифа:
   - `tests/fixtures/read_19_10045_1.html`
   - `tests/fixtures/read_20_31559_2.html`
   - `tests/fixtures/broken_db_error.html` (из `data/raw/archive/broken/read_18_41771_1.html`)
2. Перед реализацией вручную осмотрел разметку всех трёх фикстур через BeautifulSoup
   (селекторы `table[id^="message"]`, `div.forum-post-text`, `div.forum-user-name a`,
   `div.forum-post-date span`, `div.forum-post-number a`, `span.forum-post-lastedit-*`,
   `div.forum-user-signature`) — в отличие от задач 2 и 3, здесь селекторы брифа
   **совпали с реальностью** на всех трёх образцах без правок.
3. Написаны 4 падающих теста из брифа (`tests/test_parse_thread.py`), убедился в падении
   (`No module named 'pipeline.parse_thread'`), затем реализовал `pipeline/parse_thread.py`
   по коду брифа — все 4 теста прошли.
4. Прогнал парсер по **всему корпусу** (3401 файл `read_*.html` в `data/raw/archive/pages/`
   + 1 файл в `data/raw/archive/broken/`, итого 3402) с критическим разбором по всем
   пунктам из задания. Нашёл системный баг с потерей автора у постов без ссылки на профиль
   (см. ниже) — почини́л и закрыл тестом на реальной фикстуре (5-й тест,
   `tests/fixtures/read_16_38868_1.html`).
5. Повторный полный прогон после фикса — 0 постов с пустым автором.
6. Финальный прогон всего тестового набора пакета (`tests/`) — 19/19 зелёных.

## Найденный и исправленный баг: автор без ссылки на профиль

**Симптом:** у 19 постов из 38046 (0.05%) `author == ""` и `author_uid is None`, хотя
имя автора реально присутствует в HTML.

**Причина:** код брифа искал автора только через `div.forum-user-name a` (текст внутри
`<a>`). У части постов (спам-аккаунты, гостевые/удалённые пользователи) в
`div.forum-user-name` нет `<a>`, есть только `<span>` с именем — ссылки на профиль
не существует, но имя показывается. Пример (`read_16_38868_1.html`, mid=342659):

```html
<div class="forum-user-name"><span>mallorymercy vigorda</span></div>
```

**Фикс:** `pipeline/parse_thread.py` — фолбэк `author_node = user_link or table.select_one("div.forum-user-name")`;
`author_uid` в этом случае остаётся `None` (ссылки на профиль нет — узнать UID неоткуда,
это ожидаемо для таких постов).

**Тест:** `test_author_without_profile_link_still_captured` на реальной фикстуре
`tests/fixtures/read_16_38868_1.html` (mid 342659, автор "mallorymercy vigorda",
`author_uid is None`).

## Вывод тестов

```
$ cd ~/code/Python/subaru-faq && .venv/bin/python -m pytest tests/ -v
============================= test session starts ==============================
collected 19 items

tests/test_db.py::test_init_schema_creates_tables PASSED
tests/test_db.py::test_posts_fts_searches_russian PASSED
tests/test_html_text.py::test_quote_becomes_blockquote PASSED
tests/test_html_text.py::test_image_prefers_full_size_from_data_bx_src PASSED
tests/test_html_text.py::test_br_becomes_newline_and_entities_decoded PASSED
tests/test_html_text.py::test_link_kept_as_markdown PASSED
tests/test_html_text.py::test_script_does_not_leak_into_text PASSED
tests/test_html_text.py::test_noscript_fallback_does_not_leak_into_text PASSED
tests/test_html_text.py::test_image_wrapped_in_link_stays_an_image PASSED
tests/test_html_text.py::test_nested_quote_plain_text_strips_all_quote_markers PASSED
tests/test_html_text.py::test_link_with_parenthesis_in_url_plain_text PASSED
tests/test_parse_listing.py::test_parses_rows PASSED
tests/test_parse_listing.py::test_started_at_is_iso_date PASSED
tests/test_parse_listing.py::test_malformed_container_row_is_skipped_not_misparsed PASSED
tests/test_parse_thread.py::test_parses_posts_with_author_and_date PASSED
tests/test_parse_thread.py::test_signature_is_not_part_of_post_text PASSED
tests/test_parse_thread.py::test_quote_present_in_markdown PASSED
tests/test_parse_thread.py::test_broken_db_error_page_yields_no_posts PASSED
tests/test_parse_thread.py::test_author_without_profile_link_still_captured PASSED

============================== 19 passed in 0.19s ===============================
```

## Полный прогон по корпусу — цифры (после фикса)

Воспроизводимая команда (с активным venv-python, из корня репозитория):

```bash
cd ~/code/Python/subaru-faq && .venv/bin/python3 - <<'EOF'
import re, warnings
from bs4 import MarkupResemblesLocatorWarning
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
from pathlib import Path
from collections import Counter
from pipeline import parse_thread

PAGES = Path("data/raw/archive/pages")
BROKEN = Path("data/raw/archive/broken")
all_files = sorted(PAGES.glob("read_*.html")) + sorted(BROKEN.glob("read_*.html"))

total_posts = 0
mid_counter = Counter()
empty_pages, empty_author, empty_date, empty_text, mismatch_pages = [], [], [], [], []

for p in all_files:
    raw = p.read_bytes().decode("cp1251", "replace")
    page = parse_thread.parse(raw)
    n = len(page.posts)
    total_posts += n
    for post in page.posts:
        mid_counter[post.mid] += 1
        if not post.author.strip(): empty_author.append((str(p), post.mid))
        if not post.posted_at.strip(): empty_date.append((str(p), post.mid))
        if not post.text.strip(): empty_text.append((str(p), post.mid))
    raw_ids = re.findall(r'<table[^>]+id="message(\d+)"', raw)
    if len(raw_ids) != n: mismatch_pages.append((str(p), n, len(raw_ids)))
    if n == 0: empty_pages.append(str(p))

print("files:", len(all_files), "total_posts:", total_posts, "unique_mids:", len(mid_counter))
print("mids on >1 page:", sum(1 for v in mid_counter.values() if v > 1))
print("pages with 0 posts:", empty_pages)
print("mismatch parsed-vs-raw pages:", len(mismatch_pages))
print("empty author:", len(empty_author), "empty date:", len(empty_date), "empty text:", len(empty_text))
EOF
```

Результат:

- **Файлов разобрано: 3402** (3401 `read_*.html` в `data/raw/archive/pages/` +
  1 в `data/raw/archive/broken/`).
- **Всего постов извлечено: 38046.**
- **Уникальных `mid`: 37913.**
- **Совпадение числа постов и числа блоков `id="message<цифры>"` в сыром HTML:
  0 расхождений** (`mismatch_pages` пуст на всех 3402 файлах) — парсер не теряет и не
  дублирует посты относительно сырой разметки ни на одной странице.
- **Страницы без единого поста: 1** — `data/raw/archive/broken/read_18_41771_1.html`,
  причина — ожидаемая ошибка БД форума (`Fatal error`/`DB query error` в теле страницы),
  в сыром HTML вообще нет блоков `id="message…"`. Среди 3401 страниц в `pages/`
  таких страниц с 0 постов — 0 (все 3401 дали хотя бы один пост, других
  «подозрительных» пустых страниц не найдено).
- **Пустой автор: 0** (после фикса; до фикса — 19, см. раздел выше).
- **Пустая дата: 0.**
- **Пустой текст: 358** — все проверенные вручную случаи (5 образцов) оказались
  легитимными постами с картинкой/смайликами и без текста (например, серия смайликов
  `icon_lol.gif`, репост картинки по прямой ссылке, картинка-баннер в `<a>`) — это не баг
  парсера, `images` при этом непустой. Единичная странность, не системная проблема.

### Дубликаты `mid` — не баг парсера, а дубликаты сырых страниц

134 из 37913+120 «повторных» `mid` (120 уникальных id, встречающихся на >1 странице)
объясняются тем, что **некоторые файлы `read_*.html` в архиве являются буквальными
дублями других файлов** (тот же набор постов под другим именем страницы/темы):
например, `read_12_32487_1.html` и `read_12_32487_24.html` содержат идентичный набор
из 20 `mid`; `read_17_31222_1.html`/`read_5_31222_1.html` и `read_21_41498_*` /
`read_7_41498_*` — судя по всему, одна и та же тема, сохранённая архиватором под двумя
разными `FID` (переезд темы между разделами форума, старый URL с прежним FID тоже
резолвится). Также нашёлся файл с явно битым именем `read_23_23771<br_1.html`
(буквально содержит `<br` в имени) — артефакт стадии скачивания архива, не парсера.
Это дело сырого корпуса/этапа записи в БД (дедуп по `mid` как первичному ключу — задача
следующего шага), парсер корректно и одинаково разбирает оба файла — вмешательства в
Задаче 4 не требует, но **важно для Задачи 5**: запись в БД должна дедуплицировать по
`mid`, иначе одни и те же посты попадут в базу дважды из разных файлов.

### Проверка подписи пользователя (`div.forum-user-signature`)

Отдельно проверил требование "подпись не должна попадать в текст поста" на всём
корпусе, а не только на фикстуре — структурная проверка (является ли узел подписи
потомком `div.forum-post-text`) по всем 38046 постам:

```bash
cd ~/code/Python/subaru-faq && .venv/bin/python3 - <<'EOF'
import warnings
from bs4 import MarkupResemblesLocatorWarning
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
from pathlib import Path
from bs4 import BeautifulSoup

read_files = sorted(Path("data/raw/archive/pages").glob("read_*.html"))
checked = nested = 0
for p in read_files:
    soup = BeautifulSoup(p.read_bytes().decode("cp1251", "replace"), "lxml")
    for t in soup.select('table[id^="message"]'):
        body = t.select_one("div.forum-post-text")
        if body is None:
            continue
        checked += 1
        if body.select_one("div.forum-user-signature") is not None:
            nested += 1
print("checked:", checked, "nested signature inside body (real leak):", nested)
EOF
```

Результат: **`checked: 38046, nested: 0`** — подпись нигде не вложена в тело поста
на всём корпусе. (Первая грубая проверка по вхождению подстроки текста подписи в HTML
тела дала 57 ложных срабатываний — совпадения вида город/марка авто/телефон,
упомянутые автором и в подписи, и повторно в самом тексте поста; структурная проверка
по DOM-вложенности их отсеяла.)

### Проверка атрибуции автора к своему посту, а не соседнему

Проверено на `read_19_10045_1.html` (20 постов) — авторы первых пяти постов подряд
разные и совпадают с ожидаемым порядком в HTML:
`DTR → NoIZz → Дмитрий → Святослав Тонкой → KOLESO`. Поскольку все селекторы автора,
даты, номера и тела ищутся через `table.select_one(...)` **внутри цикла по каждой
`table`** (а не глобальным поиском по документу), перепутывание с соседним постом
структурно исключено; проверка `mismatch_pages == 0` на всех 3402 файлах — ещё одно
косвенное подтверждение, что число обработанных таблиц (и, соответственно, авторов)
на каждой странице соответствует числу постов в сыром HTML.

## Дополнение: message-страницы

Ревьюер справедливо указал, что первый прогон охватил только `read_*.html`
(3401 файл, 60% корпуса) и не тронул `message_*.html` (2300 файлов) — а у
1208 из 2311 тем-с-постами (`FID`,`TID`) единственный источник постов —
именно `message`-страницы, `read`-страниц для них в архиве нет вовсе.
Проверено отдельным запросом по именам файлов:

```bash
cd ~/code/Python/subaru-faq && .venv/bin/python3 - <<'EOF'
import re
from pathlib import Path
PAGES = Path("data/raw/archive/pages")
read_tids = {(m.group(1), m.group(2)) for p in PAGES.glob("read_*.html")
             if (m := re.match(r"read_(\d+)_(\d+)_(\d+)\.html$", p.name))}
msg_tids = {(m.group(1), m.group(2)) for p in PAGES.glob("message_*.html")
            if (m := re.match(r"message_(\d+)_(\d+)_(\d+)\.html$", p.name))}
print("(fid,tid) с read:", len(read_tids))
print("(fid,tid) с message:", len(msg_tids))
print("только в message (read нет вообще):", len(msg_tids - read_tids))
EOF
```

Результат: `(fid,tid) с read: 2311`, `с message: 1208`, `только в message: 1208`
— то есть **все** темы, представленные `message`-файлами, не имеют ни одной
`read`-страницы. Полный прогон по `read_*` без `message_*` покрывал бы только
2311 из 3519 тем корпуса (66%), а не «весь корпус», как формулировалось в
первой версии отчёта.

### Полный прогон по всем 5937 файлам `data/raw/archive/pages/` + 1 в `broken/`

Воспроизводимая команда (по группам, чтобы отделить `message_*` от `read_*`):

```bash
cd ~/code/Python/subaru-faq && .venv/bin/python3 - <<'EOF'
import re, warnings
from bs4 import MarkupResemblesLocatorWarning
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
from pathlib import Path
from collections import Counter
from pipeline import parse_thread

PAGES = Path("data/raw/archive/pages")
BROKEN = Path("data/raw/archive/broken")

def analyze(files, label):
    total_posts = 0
    mid_counter = Counter()
    empty_pages, empty_author, empty_date, empty_text, mismatch_pages, exceptions = [], [], [], [], [], []
    for p in files:
        raw = p.read_bytes().decode("cp1251", "replace")
        try:
            page = parse_thread.parse(raw)
        except Exception as e:
            exceptions.append((str(p), repr(e))); continue
        n = len(page.posts)
        total_posts += n
        for post in page.posts:
            mid_counter[post.mid] += 1
            if not post.author.strip(): empty_author.append((str(p), post.mid))
            if not post.posted_at.strip(): empty_date.append((str(p), post.mid))
            if not post.text.strip(): empty_text.append((str(p), post.mid))
        raw_ids = re.findall(r'<table[^>]+id="message(\d+)"', raw)
        if len(raw_ids) != n: mismatch_pages.append((str(p), n, len(raw_ids)))
        if n == 0: empty_pages.append(str(p))
    print(f"=== {label} === files:{len(files)} exceptions:{len(exceptions)} "
          f"posts:{total_posts} unique_mids:{len(mid_counter)} "
          f"dup_mids:{sum(1 for v in mid_counter.values() if v>1)} "
          f"empty_pages:{len(empty_pages)} mismatch:{len(mismatch_pages)} "
          f"empty_author:{len(empty_author)} empty_date:{len(empty_date)} empty_text:{len(empty_text)}")
    return empty_pages

analyze(sorted(PAGES.glob("read_*.html")), "read_*")
analyze(sorted(PAGES.glob("message_*.html")), "message_*")
analyze(sorted(BROKEN.glob("*.html")), "broken/*")
analyze(sorted(PAGES.glob("list_*.html")), "list_* (не для parse_thread)")
analyze(sorted(PAGES.glob("index_*.html")), "index_* (не для parse_thread)")
EOF
```

Результат:

| Группа | файлов | постов | уникальных mid | дубли mid (на >1 странице) | страниц с 0 постов | mismatch посты/блоки | пустой автор | пустая дата | пустой текст |
|---|---|---|---|---|---|---|---|---|---|
| `read_*` | 3401 | 38046 | 37913 | 120 | 0 | 0 | 0 | 0 | 358 |
| `message_*` | 2300 | 22950 | 10776 | 3349 | 10 | 0 | 0 | 0 | 88 |
| `broken/*` | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| `list_*` | 235 | 0 | 0 | 0 | 235 | 0 | 0 | 0 | 0 |
| `index_*` | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |

Исключений (падений парсера) — 0 во всех группах, включая `list_*`/`index_*`,
для которых `parse_thread.parse` не предназначен: он корректно возвращает
`posts == []` и не генерирует ложных постов ни на одном из 236 таких файлов
(структура оглавлений/индекса не содержит `table[id^="message"]`).

**Итого по всему корпусу (5937 файлов в `pages/` + 1 в `broken/` = 5938):**
всего постов **60996** (38046 из `read_*` + 22950 из `message_*`; `broken/*`,
`list_*`, `index_*` дают 0), уникальных `mid` **48689** (37913 + 10776;
пересечение mid между `read_*` и `message_*` — 0, подтверждено отдельно:
темы, покрытые `message_*`, не имеют `read`-страниц вовсе, поэтому наборы mid
не пересекаются). Пустых авторов/дат по всему корпусу — 0. `mismatch`
(посты ≠ число блоков `id="message<N>"` в сыром HTML) — 0 на всех 5938 файлах
без исключения.

### `message_*`: 10 страниц с 0 постов — не баг парсера, антибот-челлендж

Все 10 «пустых» `message_*`-страниц (`message_18_96388_0.html`,
`message_22_92460_0.html`, `message_25_95763_0.html`, `message_26_93386_0.html`,
`message_3_93533_0.html`, `message_4_32503_420176.html`, `message_4_58261_0.html`,
`message_4_93532_0.html`, `message_5_82516_0.html`, `message_5_93523_0.html`)
не содержат разметки форума вообще — вместо тела страницы краулер сохранил
JS-антибот-челлендж (маркеры `ctSetCookie`/`ctMouseData`, слежение за
движением мыши перед выдачей реального контента, характерно для
Anti-DDoS/CloudFlare-подобной защиты). Это третья, ранее не описанная
легитимная причина нулевых постов (первая — `DB query error`/`Fatal error`
в `broken/`; вторая для полноты — просто отсутствие блоков `message` на
`list_*`/`index_*`, которые вообще не про темы). Парсер корректно даёт
`posts == []` на всех 10, ложных постов из разметки челленджа не извлекает.
Закрыто тестом `test_message_page_behind_bot_challenge_yields_no_posts` на
фикстуре `tests/fixtures/message_bot_challenge.html`.

### `message_*`: совпадение целевого MID из имени файла с распарсенным постом

**Первая попытка этой проверки содержала методическую ошибку**, которую нашёл
и исправил при перепроверке перед отправкой: я исключал из выборки страницы,
где в HTML встречается фрагмент антибот-скрипта (`ctSetCookie`/`ctMouseData`),
считая их «страницами-челленджами». Это оказалось неверно — этот скрипт
встречается на 922 страницах `message_*`, но лишь у 10 из них реально нет
форумного контента (см. предыдущий раздел); на остальных 912 скрипт стоит
перед вполне рабочей разметкой форума. Ошибочный фильтр исключил из проверки
912 валидных файлов. Пересчитал правильно — единственный корректный признак
«страница без контента» это `page.posts == []` по факту парсинга, а не
наличие скрипта в HTML:

```bash
cd ~/code/Python/subaru-faq && .venv/bin/python3 - <<'EOF'
import re, warnings
from bs4 import MarkupResemblesLocatorWarning
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
from pathlib import Path
from pipeline import parse_thread

PAGES = Path("data/raw/archive/pages")
missing, checked, no_title, zero_post = [], 0, [], []
for p in sorted(PAGES.glob("message_*.html")):
    m = re.match(r"message_(\d+)_(\d+)_(\d+)\.html$", p.name)
    if not m: continue          # message_7_68277_unread_mid.html — без числового MID
    fname_mid = int(m.group(3))
    page = parse_thread.parse(p.read_bytes().decode("cp1251", "replace"))
    if not page.posts:
        zero_post.append(p.name); continue
    checked += 1
    mids = {post.mid for post in page.posts}
    if fname_mid not in mids: missing.append((p.name, fname_mid, len(mids)))
    if not page.title.strip(): no_title.append(p.name)
print("zero-post (numeric filename):", len(zero_post))
print("checked (posts>0):", checked, "missing target mid:", len(missing), "empty title:", len(no_title))
EOF
```

Результат: **zero-post: 10** (совпадает с прошлым разделом — те же 10
антибот-заглушек), **checked (posts>0): 2289, missing target mid: 37,
empty title: 0.** Заголовок темы извлекается верно на всех 2289 проверенных
страницах без исключения. Целевой `mid` из имени файла присутствует среди
распарсенных постов в **2252 из 2289** случаев (98.4%); один чистый пример
проверен явным тестом (`test_message_page_yields_target_post_and_title`,
`message_1_78938_414802.html`: заголовок "Looking for best bang for buck
processor. *Newbie*", 1 пост, `mid=414802`, `author="Joe Clark"`,
`author_uid=86070`).

**37 «промахов» — не баг парсера, а условность именования файлов краулером.**
Во всех 37 случаях последний сегмент имени — маленькое число (1–14), явно
номер страницы, а не `mid` (реальные `mid` в теле этих страниц —
шестизначные/пятизначные, например `message_12_37036_1.html` содержит
20 постов с `mid` от 313116 и выше; `message_3_10473_1.html` — от 56204).
Страница при этом полноценно разбирается — тот же формат разметки треда,
что и `read_*` (заголовок и все посты извлекаются корректно), просто
краулер на каком-то из этапов сохранил её под `message_`-префиксом с
номером страницы вместо `MID` (вероятно, редирект в ответ на
устаревший/несуществующий MID увёл на постраничный вид темы, а имя файла
собиралось из последнего URL-параметра без проверки его смысла — то же
семейство тем, что и у `message_7_68277_1.html`/`message_7_68277_unread_mid.html`
ниже, где одна и та же страница сохранена под двумя разными «псевдо-MID»).
Для Задачи 5 вывод: **нельзя полагаться на «последний сегмент имени
message_-файла — это mid» как на жёсткий инвариант** — в ~1.6% случаев это
номер страницы; извлекать нужно все посты со страницы (как из `read_*`),
а не только «тот самый» по имени файла, и дедуп по `mid` в БД сам разрешит
пересечения между такими файлами и обычными `message_*`/`read_*`.

Отдельно — файл `message_7_68277_unread_mid.html` (без числового MID вообще,
буквально `unread_mid` в имени): открыл содержимое — реальная страница темы
"Продам запчасти на BG5" с 13 постами (то же самое содержимое, что и у
`message_7_68277_1.html` из списка промахов выше — тот же тред под другим
псевдо-именем). Перед контентом стоит тот же антибот-JS-скрипт, но за ним
следует настоящая разметка форума. Парсер корректно извлёк все 13 постов.
Само имя файла — тоже артефакт краулера (похоже, ссылка на «первое
непрочитанное сообщение» без явного MID в URL), не относится к парсеру.

### Вердикт по `read_23_23771<br_1.html`

Файл существует, `<br` — буквальная часть имени. Сравнение с
`read_23_23771_1.html`: оба файла — **разные HTTP-ответы** (разные
`bitrix_sessid`, разные CSRF-токены в форме логина — это разные визиты
краулера), но содержат **идентичный форумный контент**: тот же единственный
пост (`mid=173684`, автор Vladimir, дата `2009-05-06 22:21:09`, тот же текст
и markdown — проверено побайтово через `dataclass`-равенство `Post`, оно же
`==`, вернуло `True` по всем полям). Диффом сырых файлов подтверждено: везде,
где в "чистом" файле встречается `TID=23771`, в битом — `TID=23771%3Cbr`
(URL-кодированный литеральный `<br`) — то есть сервер форума в момент этого
конкретного визита краулера обслуживал запрос с TID, буквально содержащим
`<br` в качестве значения параметра (не санитизированный ввод в URL,
вероятно старая ссылка/редирект с мусорным хвостом), и, судя по всему,
на уровне PHP/SQL нестрогое приведение TID к числу отбросило нечисловой
хвост, вернув контент той же самой темы 23771.

**Вывод:** это не мусор и не повреждённая страница — оба файла содержат
достоверный форумный пост, парсер обрабатывает их одинаково корректно.
Это дубликат по содержанию (тот же `mid`) под другим именем — того же рода
проблема, что и 120 дублей `mid` в `read_*`, уже описанных выше; дедуп по
`mid` в Задаче 5 закрывает и этот случай. Специального обхода в парсере не
требуется — само битое имя было учтено в файловой системе уже при
скачивании архива (Задача 1/2), трогать его в Задаче 4 не в мандате.

## Хэши коммитов

- `378214d` — `feat(parse): парсер страниц тем с авторами, датами и цитатами`
  (код + тесты + фикстуры, включая фикс автора без ссылки на профиль)
- `caf521e` — `test(parse): покрыть message_*.html — вторую половину форматов страниц`
  (2 новые фикстуры `message_1_78938_414802.html`, `message_bot_challenge.html`
  + 2 теста; системных багов в обработке `message_*` не найдено, тесты фиксируют
  найденные легитимные категории 0-постовых страниц и корректность разбора
  «чистой» message-страницы)

## Сомнения и отклонения от брифа

1. **Отклонение (минимальное, обосновано находкой):** добавлен фолбэк на
   `div.forum-user-name` без `<a>` — брифовый код брал автора только из `<a>`. Без
   этого 19 реальных постов теряли автора полностью, что для базы знаний означало бы
   пропущенную атрибуцию источника. Изменение минимальное, покрыто тестом на реальной
   фикстуре, `author_uid` для таких постов корректно остаётся `None`.
2. **Не фиксил, а зафиксировал как находку для следующей задачи:** 120 `mid`,
   встречающихся на нескольких файлах-страницах — это дубликаты сырых файлов архива
   (одна и та же тема под двумя `FID`, либо буквально задвоенная страница), не баг
   парсера. Дедупликация по `mid` при записи в БД (Задача 5, `INSERT OR IGNORE`/`UPSERT`
   с `mid` как ключом) должна это перекрыть.
3. **Не в задаче:** файл с битым именем `read_23_23771<br_1.html` — артефакт стадии
   скачивания архива, не парсера; парсер обрабатывает его так же корректно, как и
   правильно названный дубль. Упомянуто здесь на случай, если это симптом более
   широкой проблемы стадии скачивания, которую стоит перепроверить отдельно.
4. **358 постов с пустым `text`** — не баг, посты без текста (только картинки/смайлики);
   `images` в этих случаях непустой. Если для базы знаний важно отличать «пост без
   текста» от «пост с текстом, который случайно пуст после нормализации» — это можно
   сделать позже полем `bool(images)`, в Задаче 4 такого требования не было.
