import http.server
import socketserver
import os
import sys
import webbrowser
from pathlib import Path

PORT = int(os.environ.get('PORT', '8000'))
ROOT = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, format, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {self.address_string()} -> {format % args}\n")


def main():
    os.chdir(ROOT)
    handler = Handler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        url = f"http://localhost:{PORT}/"
        print(f"\n  ПЗФ Вінниччини — локальний сервер")
        print(f"  Папка: {ROOT}")
        print(f"  Адреса: {url}")
        print(f"  Натисніть Ctrl+C, щоб зупинити.\n")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Сервер зупинено.")
            sys.exit(0)


if __name__ == '__main__':
    main()
