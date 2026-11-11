"""Local singleton and a small overwritten boot counter. This does not provide HA."""
import json
import os
import tempfile
from pathlib import Path

from core.camera_catalog import service_path


EPOCH_STRIDE = 1 << 32
MAX_GENERATION = (1 << 21) - 1  # Keep assignment epochs within exact JSON integer range.


class LocalMasterSession:
    def __init__(self, state_path):
        self.path = service_path(state_path)
        self.lock = None
        self.generation = 0

    @property
    def epoch_base(self):
        return self.generation * EPOCH_STRIDE

    def open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        lock_existed = lock_path.exists()
        self.lock = lock_path.open("a+b")
        try:
            self.lock.seek(0, os.SEEK_END)
            if not self.lock.tell():
                self.lock.write(b"0")
                self.lock.flush()
            self.lock.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("Another local master is using this runtime state file") from None
            if self.path.exists():
                try:
                    value = json.loads(self.path.read_text(encoding="utf-8"))
                    if set(value) != {"version", "generation"} or type(value["version"]) is not int or value["version"] != 1 or type(value["generation"]) is not int or value["generation"] < 1:
                        raise ValueError()
                    previous = value["generation"]
                except Exception:
                    raise RuntimeError("Invalid master boot state; restore it instead of resetting epochs") from None
            else:
                if lock_existed:
                    raise RuntimeError("Master boot state is missing; restore it instead of reusing old epochs")
                previous = 0
            if previous >= MAX_GENERATION:
                raise RuntimeError("Master generation exhausted; migrate epoch format before restarting")
            self.generation = previous + 1
            payload = json.dumps({"version": 1, "generation": self.generation}) + "\n"
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                                 prefix=".cluster-boot-", suffix=".tmp", delete=False) as target:
                    temporary = Path(target.name)
                    target.write(payload)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary, self.path)
                if os.name != "nt":
                    fd = os.open(self.path.parent, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.lock is not None:
            self.lock.close()  # OS releases the advisory lock even after process death.
            self.lock = None
