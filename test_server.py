import unittest
import http.client
import os
import threading
import time
from server import PORT, ROOT, Handler
import socketserver

class ServerThread(threading.Thread):
    def __init__(self, port):
        super().__init__()
        self.port = port
        self.httpd = None
        self.daemon = True

    def run(self):
        with socketserver.TCPServer(("", self.port), Handler) as httpd:
            self.httpd = httpd
            httpd.serve_forever()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()

class TestWebApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = PORT + 1  # avoid conflict with main server
        cls.server_thread = ServerThread(cls.port)
        cls.server_thread.start()
        time.sleep(1)  # wait for server to start

    @classmethod
    def tearDownClass(cls):
        cls.server_thread.stop()
        time.sleep(0.5)

    def test_index_html_served(self):
        conn = http.client.HTTPConnection("localhost", self.port)
        conn.request("GET", "/index.html")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"<!DOCTYPE html>", resp.read())
        conn.close()

    def test_css_served(self):
        conn = http.client.HTTPConnection("localhost", self.port)
        conn.request("GET", "/assets/css/styles.css")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"body", resp.read())
        conn.close()

    def test_js_served(self):
        conn = http.client.HTTPConnection("localhost", self.port)
        conn.request("GET", "/assets/js/app.js")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"function", resp.read())
        conn.close()

    def test_404(self):
        conn = http.client.HTTPConnection("localhost", self.port)
        conn.request("GET", "/notfound12345.html")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 404)
        conn.close()

if __name__ == "__main__":
    unittest.main()
