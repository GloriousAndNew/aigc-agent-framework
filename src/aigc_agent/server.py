"""Local development JSON API; do not expose directly to the internet."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .core import Engine


def handler_for(engine):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/health":
                return self.send_json(200, {"status": "ok", "mode": "mock"})
            if path.startswith("/tasks/"):
                task = engine.get(path[len("/tasks/"):])
                return self.send_json(200 if task else 404, task or {"error": "not found"})
            self.send_json(404, {"error": "not found"})

        def do_POST(self):
            if urlsplit(self.path).path != "/tasks":
                return self.send_json(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 32768:
                    return self.send_json(413, {"error": "body must contain 1-32768 bytes"})
                self.connection.settimeout(10)
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                task_id = engine.submit(request)
                self.send_json(202, {"id": task_id, "status_url": "/tasks/" + task_id})
            except (ValueError, UnicodeError):
                self.send_json(400, {"error": "invalid JSON, kind or prompt"})
            except OverflowError:
                self.send_json(429, {"error": "task queue is full"})

        def log_message(self, format, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", default="data")
    args = parser.parse_args()
    engine = Engine(args.data)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(engine))
    print(f"Mock API: http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        engine.close()


if __name__ == "__main__":
    main()
