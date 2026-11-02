"""Exercise the HTTP boundary where browsers choose Chinese report encoding."""
import threading
import unittest
from urllib.request import ProxyHandler, build_opener

from py_view.results_dashboard.server import create_server


class ReportEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server("127.0.0.1", 0)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.client = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.worker.join()
        cls.server.server_close()

    def test_chinese_report_inline_and_download_are_utf8(self):
        for route in ("/tmq/REPORT.md", "/download?key=tmq-report"):
            with self.subTest(route=route), self.client.open(self.base + route) as response:
                self.assertEqual(response.headers.get_content_charset(), "utf-8")
                self.assertIn("新材料", response.read().decode(response.headers.get_content_charset()))
                if route.startswith("/download"):
                    self.assertIn("attachment", response.headers["Content-Disposition"])
                else:
                    self.assertEqual(response.headers.get_content_type(), "text/plain")
                    self.assertEqual(response.headers["Cache-Control"], "no-cache")

    def test_binary_figure_keeps_its_bytes_and_type(self):
        with self.client.open(self.base + "/tmq/results/full_hysteresis.png") as response:
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertTrue(response.read().startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
