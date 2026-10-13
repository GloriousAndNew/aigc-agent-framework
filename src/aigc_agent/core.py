"""Persistent tasks and injectable generation providers, using only stdlib."""
import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


def now():
    return datetime.now(timezone.utc).isoformat()


def validate(request):
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    if request.get("kind") not in ("image", "video", "audio"):
        raise ValueError("kind must be image, video or audio")
    prompt = request.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        raise ValueError("prompt must contain 1-4000 characters")
    return {"kind": request["kind"], "prompt": prompt.strip()}


class Provider(Protocol):
    def generate(self, request: dict, output_dir: Path) -> dict:
        """Return JSON-serializable metadata; write artifacts into output_dir."""
        ...


class MockProvider:
    """Produces test manifests, never pretends to generate real media."""
    def generate(self, request, output_dir):
        result = {
            "simulated": True,
            "provider": "mock",
            "kind": request["kind"],
            "prompt": request["prompt"],
            "message": "Workflow test only: no image, video or audio was generated.",
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result


class Engine:
    """Single-process engine with bounded outstanding work and durable records."""
    def __init__(self, root="data", provider=None, workers=2, capacity=100):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "tasks.sqlite3"
        self.provider = provider or MockProvider()
        self.lock = threading.Lock()
        self.capacity = capacity
        self.closed = False
        with self.connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, request TEXT NOT NULL,
                result TEXT, error TEXT, created_at TEXT, updated_at TEXT)""")
            # Never resubmit a potentially billed generation silently after a crash.
            con.execute("UPDATE tasks SET status='interrupted', error=?, updated_at=? "
                        "WHERE status IN ('queued','running')",
                        ("Service restarted; explicitly create a new task to retry.", now()))
        self.pool = ThreadPoolExecutor(max_workers=workers)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def submit(self, request):
        request = validate(request)
        task_id = uuid.uuid4().hex
        with self.lock:
            if self.closed:
                raise RuntimeError("engine is closed")
            with self.connect() as con:
                count = con.execute("SELECT COUNT(*) FROM tasks WHERE status IN "
                                    "('queued','running')").fetchone()[0]
                if count >= self.capacity:
                    raise OverflowError("task queue is full")
                timestamp = now()
                con.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?)",
                            (task_id, "queued", json.dumps(request), None, None,
                             timestamp, timestamp))
            self.pool.submit(self.run, task_id, request)
        return task_id

    def update(self, task_id, status, result=None, error=None):
        with self.connect() as con:
            con.execute("UPDATE tasks SET status=?,result=?,error=?,updated_at=? WHERE id=?",
                        (status, json.dumps(result) if result is not None else None,
                         error, now(), task_id))

    def run(self, task_id, request):
        self.update(task_id, "running")
        try:
            result = self.provider.generate(request, self.root / "outputs" / task_id)
            self.update(task_id, "succeeded", result=result)
        except Exception:
            # Do not expose provider exceptions: they can contain credentials.
            self.update(task_id, "failed", error="Generation failed; inspect the provider privately.")

    def get(self, task_id):
        with self.connect() as con:
            row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            return None
        task = dict(row)
        for field in ("request", "result"):
            if task[field] is not None:
                task[field] = json.loads(task[field])
        return task

    def close(self):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=True)
