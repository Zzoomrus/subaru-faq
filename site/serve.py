"""Локальный предпросмотр собранного сайта (public/) с «чистыми» адресами, как на GitHub Pages:
/карта-базы -> карта-базы.html, /статьи/vin/ -> index.html. Запуск: python3 site/serve.py [порт]."""
import http.server
import os
import sys
import urllib.parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def translate_path(self, path):
        path = urllib.parse.unquote(path.split("?", 1)[0].split("#", 1)[0])
        # baseUrl сайта — zzoomrus.github.io/subaru-faq, ссылки абсолютные с /subaru-faq/
        if path == "/subaru-faq" or path.startswith("/subaru-faq/"):
            path = path[len("/subaru-faq"):] or "/"
        full = os.path.join(ROOT, path.lstrip("/"))
        if os.path.isdir(full):
            return os.path.join(full, "index.html")
        if not os.path.exists(full) and os.path.exists(full + ".html"):
            return full + ".html"
        return full

    def log_message(self, fmt, *args):  # тише
        if "404" in (args[1] if len(args) > 1 else ""):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
