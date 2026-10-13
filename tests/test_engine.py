import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from aigc_agent.core import Engine
from aigc_agent.server import handler_for


class EngineTests(unittest.TestCase):
    def test_results_are_persistent_and_explicitly_mock(self):
        with tempfile.TemporaryDirectory() as root:
            engine = Engine(root)
            ids = [engine.submit({"kind": kind, "prompt": "咖啡宣传"})
                   for kind in ("image", "video", "audio")]
            engine.close()
            reopened = Engine(root)
            try:
                for task_id in ids:
                    task = reopened.get(task_id)
                    self.assertEqual(task["status"], "succeeded")
                    self.assertTrue(task["result"]["simulated"])
                    self.assertTrue((Path(root) / "outputs" / task_id / "result.json").exists())
            finally:
                reopened.close()

    def test_capacity_and_provider_failure(self):
        gate = threading.Event()
        class FailingProvider:
            def generate(self, request, output_dir):
                gate.wait(5)
                raise RuntimeError("secret-key")
        with tempfile.TemporaryDirectory() as root:
            engine = Engine(root, FailingProvider(), capacity=1)
            try:
                task_id = engine.submit({"kind": "video", "prompt": "test"})
                with self.assertRaises(OverflowError):
                    engine.submit({"kind": "audio", "prompt": "test"})
            finally:
                gate.set()
                engine.close()
            task = engine.get(task_id)
            self.assertEqual(task["status"], "failed")
            self.assertNotIn("secret-key", task["error"])

    def test_http_api_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as root:
            engine = Engine(root)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(engine))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                request = Request(base + "/tasks", data=json.dumps(
                    {"kind": "image", "prompt": "test"}).encode(), method="POST")
                with urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 202)
                    task_id = json.load(response)["id"]
                with urlopen(base + "/tasks/" + task_id, timeout=5) as response:
                    self.assertEqual(json.load(response)["request"]["kind"], "image")
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(base + "/tasks", data=b'{}', method="POST"), timeout=5)
                self.assertEqual(caught.exception.code, 400)
                caught.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                engine.close()


if __name__ == "__main__":
    unittest.main()
