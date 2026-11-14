"""Run: python fake_logic.py. Receive POST /ai-data on port 8000."""
import json
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LOG_FILE = Path(__file__).with_name("ai-data.jsonl")

class Handler(BaseHTTPRequestHandler):
    previous_received = None

    def log_message(self, *_):
        pass

    def do_POST(self):
        if self.path != "/ai-data":
            self.send_error(404)
            return
        now = time.perf_counter()
        received_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        gap_ms = None if Handler.previous_received is None else round(
            (now - Handler.previous_received) * 1000, 3)
        Handler.previous_received = now
        line = json.dumps({"received_at": received_at, "gap_ms": gap_ms,
                           "body": body.decode("utf-8", errors="replace")}, ensure_ascii=False)
        with LOG_FILE.open("a", encoding="utf-8") as log:
            log.write(line + "\n")
        print(line, flush=True)
        response = b'{"status":"success","message":"Data updated"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

if __name__ == "__main__":
    print(f"POST http://127.0.0.1:8000/ai-data | Log: {LOG_FILE}", flush=True)
    with HTTPServer(("0.0.0.0", 8000), Handler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
