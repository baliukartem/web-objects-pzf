import unittest
from server import Handler
from http.server import BaseHTTPRequestHandler
from io import BytesIO
import sys

class DummyRequest:
    def makefile(self, *args, **kwargs):
        return BytesIO()

class DummyServer:
    pass

class TestHandlerUnit(unittest.TestCase):
    def setUp(self):
        self.output = BytesIO()
        self.handler = Handler(DummyRequest(), ('127.0.0.1', 0), DummyServer())
        self.handler.wfile = self.output
        self.handler.rfile = BytesIO()
        self.handler.request_version = 'HTTP/1.1'
        self.handler.command = 'GET'
        self.handler.path = '/index.html'
        self.handler.requestline = 'GET /index.html HTTP/1.1'

    def test_end_headers_sets_no_cache(self):
        self.handler.send_response(200)
        self.handler.end_headers()
        headers = self.handler._headers_buffer
        header_str = b''.join(headers).decode('utf-8')
        self.assertIn('Cache-Control: no-cache, no-store, must-revalidate', header_str)
        self.assertIn('Pragma: no-cache', header_str)
        self.assertIn('Expires: 0', header_str)

    def test_log_message_format(self):
        # Capture stderr
        old_stderr = sys.stderr
        sys.stderr = BytesIO()
        self.handler.log_message("%s %s", 200, 'OK')
        sys.stderr.seek(0)
        log = sys.stderr.read().decode('utf-8')
        sys.stderr = old_stderr
        self.assertIn('-> 200 OK', log)

if __name__ == '__main__':
    unittest.main()
