"""A local webhook receiver that appends every JSON body it receives to a file (one JSON object per line).

python -m retail_ai.dq.mock_webhook --port 8765 --out build/dq/alerts.jsonl
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_server(out: Path, port: int = 0) -> ThreadingHTTPServer:
    out.parent.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(json.loads(body)) + "\n")
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve_in_background(out: Path) -> tuple[ThreadingHTTPServer, str]:
    server = make_server(out)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/hook"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--out", type=Path, default=Path("build/dq/alerts.jsonl"))
    a = ap.parse_args()
    server = make_server(a.out, a.port)
    print(f"listening on http://127.0.0.1:{a.port}/hook, writing to {a.out}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
