#!/usr/bin/env python3
"""
Static file server with live-reload support.
Watches the project directory for changes and notifies the browser via SSE.
"""
import os, time, threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle each request in a separate thread so SSE never blocks image loads."""
    daemon_threads = True

WATCH_DIR = os.path.dirname(os.path.abspath(__file__))
WATCH_EXTS = {".html", ".js", ".css"}
PORT = 8080

# Shared state
_last_modified = 0
_clients = []
_clients_lock = threading.Lock()

def scan_mtime():
    latest = 0
    for root, _, files in os.walk(WATCH_DIR):
        # skip hidden dirs like .claude
        if any(p.startswith('.') for p in root.replace(WATCH_DIR, '').split(os.sep)):
            continue
        for f in files:
            if os.path.splitext(f)[1].lower() in WATCH_EXTS:
                try:
                    t = os.path.getmtime(os.path.join(root, f))
                    if t > latest:
                        latest = t
                except OSError:
                    pass
    return latest

def watcher():
    global _last_modified
    _last_modified = scan_mtime()
    while True:
        time.sleep(0.5)
        t = scan_mtime()
        if t > _last_modified:
            _last_modified = t
            with _clients_lock:
                for q in list(_clients):
                    q.append(True)

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WATCH_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/__reload":
            self._sse()
        else:
            super().do_GET()

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        queue = []
        with _clients_lock:
            _clients.append(queue)
        try:
            while True:
                if queue:
                    queue.pop()
                    self.wfile.write(b"data: reload\n\n")
                    self.wfile.flush()
                else:
                    # heartbeat every 2 s keeps connection alive
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                time.sleep(1)
        except Exception:
            pass
        finally:
            with _clients_lock:
                if queue in _clients:
                    _clients.remove(queue)

    def log_message(self, fmt, *args):
        # suppress per-request noise; only show start message
        pass

if __name__ == "__main__":
    threading.Thread(target=watcher, daemon=True).start()
    print(f"Serving at http://localhost:{PORT}  (live reload active)")
    ThreadedHTTPServer(("", PORT), Handler).serve_forever()
