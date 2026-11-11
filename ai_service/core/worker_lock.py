"""Prevent two local AI instances from using the same worker identity."""
import hashlib
import os
from pathlib import Path


class WorkerLock:
    def __init__(self, worker_id):
        digest = hashlib.sha256(worker_id.encode("utf-8")).hexdigest()[:24]
        self.path = Path(__file__).resolve().parents[1] / "runtime" / f"worker-{digest}.lock"
        self.handle = None

    def open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            self.handle.seek(0, os.SEEK_END)
            if not self.handle.tell():
                self.handle.write(b"0")
                self.handle.flush()
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.close()
            raise RuntimeError("Another local AI instance is using this WORKER_ID") from None

    def close(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None
