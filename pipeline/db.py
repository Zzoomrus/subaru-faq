import sqlite3
from pathlib import Path

# `posts` хранит тело поста в трёх видах, и это намеренно:
#   html     — исходный фрагмент `div.forum-post-text`, из него в любой
#              момент можно пере-отрендерить всё остальное без пере-краулинга;
#   markdown — то, что читает человек в заметке зеркала: цитаты остаются
#              блокквотами, ссылки — ссылками с адресом (дефект I1 ревью:
#              раньше эта колонка не существовала вовсе, и в заметку шёл
#              plain_text, где цитата чужих слов неотличима от слов автора);
#   text     — плоский текст для полнотекстового поиска (`posts_fts` строится
#              именно по нему) и для механической проверки дословных цитат
#              в статьях следующей фазы.
SCHEMA = """
CREATE TABLE IF NOT EXISTS sections (
    fid INTEGER PRIMARY KEY, title TEXT);
CREATE TABLE IF NOT EXISTS threads (
    tid INTEGER PRIMARY KEY, fid INTEGER, title TEXT, author TEXT,
    started_at TEXT, replies_expected INTEGER, views INTEGER, pages_expected INTEGER);
CREATE TABLE IF NOT EXISTS posts (
    mid INTEGER PRIMARY KEY, tid INTEGER, page_no INTEGER, author TEXT, author_uid INTEGER,
    posted_at TEXT, number TEXT, html TEXT, markdown TEXT, text TEXT,
    edited_by TEXT, edited_at TEXT);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mid INTEGER, kind TEXT, url TEXT,
    local_path TEXT, status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS pages (
    key TEXT PRIMARY KEY, file TEXT, url TEXT, snapshot_ts TEXT, tid INTEGER, page_no INTEGER);
-- FAQ (Ф2, задача 6): раздел архивирован ДВУМЯ движками разом (см. отчёт
-- задачи 5) — современным Bitrix (`ELEMENT_ID`) и старым самописным
-- (`nr`/`catnr`/`prog`). Их номера — НЕЗАВИСИМЫЕ пространства имён, которые
-- на живом корпусе реально пересекаются (17 из 177 файлов, разный контент
-- под одним числом — см. task-6-report.md), поэтому первичный ключ таблицы
-- составной (engine, nr), а не просто nr. `catnr` осмыслен только для
-- старого движка (Bitrix-адрес его не несёт) — сознательное отклонение от
-- брифа (тот писан до открытия двух движков в задаче 5).
-- `title` (задача 6, ревизия по дефекту): у части страниц Bitrix заголовок
-- h1 — название темы, а не сам вопрос (настоящий вопрос лежал ВНУТРИ тела
-- ответа под собственной меткой "Вопрос:" — см. `parse_faq._split_embedded_
-- qa`); NULL — заголовок и есть вопрос (старый движок всегда, Bitrix — где
-- дублирования не было или заголовок совпал с вопросом из тела).
-- `answer_text` — плоский текст ответа (`html_text.plain_text_from_markdown`
-- от `answer_md`), ровно тот же смысл, что у `posts.text`: по нему строится
-- поиск (`faq_fts`). До этой правки (дефект I1 итогового ревью Ф2) плоского
-- текста и полнотекстового индекса не было ни у FAQ, ни у блогов — главная
-- механика следующей фазы (найти фразу -> сослаться -> сверить дословность)
-- была применима к одному источнику из трёх. Каноном ДОСЛОВНОЙ сверки при
-- этом остаётся тело заметки, а не это поле (Ruling 30, `docs/
-- контракт-зеркала.md`): у постов форума `text` и `markdown` расходятся у
-- 56% записей, и у FAQ/блогов разойдутся тем же способом.
CREATE TABLE IF NOT EXISTS faq (
    engine TEXT, nr INTEGER, catnr INTEGER, prog TEXT, category TEXT,
    question TEXT, answer_md TEXT, source_url TEXT, snapshot_ts TEXT,
    title TEXT, answer_text TEXT,
    PRIMARY KEY (engine, nr));
CREATE TABLE IF NOT EXISTS faq_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT, engine TEXT, nr INTEGER, url TEXT, local_path TEXT);
CREATE INDEX IF NOT EXISTS idx_faq_images_entry ON faq_images(engine, nr);
-- Блоги (Ф2, задача 7): движок Bitrix "Blog". Ключ записи — составной
-- (blog, post_id), а не просто post_id: разведка задачи 7 нашла, что
-- post_id УНИКАЛЕН только внутри одного блога (слага) — на живом корпусе
-- 10 номеров реально пересекаются между блогами `remont`/`remontSubaru`
-- (см. task-7-report.md, тот же класс находки, что и (engine, nr) у FAQ в
-- задаче 6). `is_excerpt` — запись восстановлена только из выдержки в ленте
-- (`page=blog`), отдельной страницы `page=post` для неё не сохранилось;
-- `truncated` — выдержка сама обрезана меткой "Читать подробнее..." (текст
-- заведомо неполный, честная пометка, а не потеря парсера). `tags` — JSON-
-- список строк (текстовых меток `blog-post-tag`), не отдельная таблица:
-- меток на запись мало (медиана 0-1), заводить M:N ради этого не стоило.
-- `declared_comments` — счётчик "Комментариев: N" со страницы, НЕ то же
-- самое, что число строк в `blog_comments`: разведка задачи 7 нашла его
-- ненадёжным (расходится с реально распарсенным числом на 17 из 468
-- нераспагинированных записей, см. task-7-report.md) — хранится только
-- для диагностики будущих доборов, ничего не решает и нигде не считается.
-- `body_text` — плоский текст записи для поиска (`blog_fts`), см. комментарий
-- к `faq.answer_text` выше.
CREATE TABLE IF NOT EXISTS blog_posts (
    blog TEXT, post_id INTEGER, title TEXT, author TEXT, posted_at TEXT,
    body_md TEXT, tags TEXT, source_url TEXT, snapshot_ts TEXT,
    is_excerpt INTEGER DEFAULT 0, truncated INTEGER DEFAULT 0, declared_comments INTEGER,
    body_text TEXT,
    PRIMARY KEY (blog, post_id));
-- Картинки записи и её КОММЕНТАРИЕВ (только содержательные —
-- `attachments.classify` уже отсеял хром движка на этапе разбора, см.
-- `parse_blog.py`), тот же паттерн, что и `faq_images`. `comment_id` — NULL
-- у картинок самой записи, номер комментария у картинок комментария
-- (находка M1 итогового ревью Ф2: раньше картинки комментариев не
-- собирались вовсе — генератор звал `render_post_body(text_md, {})` с пустым
-- словарём, и любая картинка комментария становилась пометкой «не
-- сохранилось» даже когда файл лежал в архиве Ф0/Ф1; хуже того, её адрес
-- никуда не писался, то есть будущий добор о нём не узнал бы).
CREATE TABLE IF NOT EXISTS blog_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT, blog TEXT, post_id INTEGER, url TEXT, local_path TEXT,
    comment_id INTEGER);
CREATE INDEX IF NOT EXISTS idx_blog_images_entry ON blog_images(blog, post_id);
-- Комментарии — только у записей, сохранившихся отдельной страницей
-- (лента комментариев не показывает вовсе, см. task-7-report.md). `depth`
-- — уровень вложенности ответа (из `padding-left` разметки, шаг 2.5em),
-- `parent_id` — номер комментария, на который отвечают (`NULL` — комментарий
-- верхнего уровня). Постраничная разбивка комментариев (`pagen=N` в URL)
-- схлопнута в загрузчике ДО записи сюда — здесь уже полный, слитый список.
CREATE TABLE IF NOT EXISTS blog_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, blog TEXT, post_id INTEGER,
    comment_id INTEGER, parent_id INTEGER, depth INTEGER,
    author TEXT, posted_at TEXT, text_md TEXT);
CREATE INDEX IF NOT EXISTS idx_blog_comments_entry ON blog_comments(blog, post_id);
CREATE INDEX IF NOT EXISTS idx_posts_tid ON posts(tid);
CREATE INDEX IF NOT EXISTS idx_attach_mid ON attachments(mid);
CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    text, mid UNINDEXED, content='posts', content_rowid='mid');
CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
    INSERT INTO posts_fts(rowid, text) VALUES (new.mid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, text) VALUES('delete', old.mid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS posts_au AFTER UPDATE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, text) VALUES('delete', old.mid, old.text);
    INSERT INTO posts_fts(rowid, text) VALUES (new.mid, new.text);
END;
-- Поиск по FAQ и блогам (дефект I1 итогового ревью Ф2). Устройство ДРУГОЕ,
-- чем у `posts_fts`, и сознательно: там внешнее содержимое (`content='posts'`
-- + `content_rowid`) плюс три триггера — это оправдано на 48 689 постах,
-- где дублировать текст в индексе значит удвоить базу. Здесь 174 записи FAQ
-- и 528 записей блогов: обычная (не внешняя) fts5-таблица, наполняемая
-- целиком в конце загрузки (`rebuild_search_index`). Причина не только в
-- размере — у обеих таблиц СОСТАВНОЙ ключ (`engine, nr` и `blog, post_id`),
-- а внешнее содержимое fts5 требует одного INTEGER rowid, то есть пришлось
-- бы выдумывать искусственный (и следить, чтобы он не менялся между
-- пересборками базы). Ключ записи лежит в самой FTS-таблице колонками
-- UNINDEXED — по нему находится и заметка зеркала, и строка исходной
-- таблицы.
-- Вопрос FAQ и название записи блога проиндексированы вместе с телом
-- отдельными колонками: искать по формулировке вопроса Ф3 будет не реже,
-- чем по тексту ответа (`SELECT ... FROM faq_fts WHERE faq_fts MATCH
-- 'question: тормоза'`).
CREATE VIRTUAL TABLE IF NOT EXISTS faq_fts USING fts5(
    question, answer, engine UNINDEXED, nr UNINDEXED);
CREATE VIRTUAL TABLE IF NOT EXISTS blog_fts USING fts5(
    title, body, blog UNINDEXED, post_id UNINDEXED);
"""

def connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def rebuild_search_index(conn: sqlite3.Connection) -> dict[str, int]:
    """Пере-наполняет `faq_fts`/`blog_fts` из таблиц-источников целиком.

    Полная пересборка, а не триггеры (см. комментарий в SCHEMA): на 174 + 528
    записях она занимает миллисекунды, идемпотентна по определению и не может
    разойтись с источником — а разошедшийся индекс, который никто не
    заметил, это ровно тот класс ошибки, из-за которого поиск отдаёт «фразы
    нет» на тексте, где она есть. Зовётся в конце `parse_faq.load_all`/
    `parse_blog.load_all`, то есть каждый раз, когда содержимое таблиц могло
    измениться.

    `posts_fts` здесь не трогается: у него внешнее содержимое и триггеры,
    он поддерживается сам (и пересборка 48 689 постов стоила бы заметно
    дороже нуля).
    """
    conn.execute("DELETE FROM faq_fts")
    conn.execute("INSERT INTO faq_fts(question, answer, engine, nr) "
                 "SELECT COALESCE(question, ''), COALESCE(answer_text, ''), engine, nr FROM faq")
    conn.execute("DELETE FROM blog_fts")
    conn.execute("INSERT INTO blog_fts(title, body, blog, post_id) "
                 "SELECT COALESCE(title, ''), COALESCE(body_text, ''), blog, post_id FROM blog_posts")
    conn.commit()
    return {"faq_fts": conn.execute("SELECT count(*) FROM faq_fts").fetchone()[0],
            "blog_fts": conn.execute("SELECT count(*) FROM blog_fts").fetchone()[0]}
