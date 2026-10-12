"""Serve only the active trial HTML and vendored libraries, never the
adjacent grading sidecars."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import unquote, urlsplit

VENDOR_DIR = (Path(__file__).parent / "vendor").resolve()


def _resolve_vendor_file(url_path):
    """Return the vendor file Path for "/vendor/<name>", or None if it is a
    sidecar, a traversal attempt, or escapes VENDOR_DIR entirely.
    """
    if not url_path.startswith("/vendor/"):
        return None
    name = unquote(url_path[len("/vendor/"):])
    if not name or "/" in name or name.endswith(".json"):
        return None
    candidate = (VENDOR_DIR / name).resolve()
    if candidate.parent != VENDOR_DIR or not candidate.is_file():
        return None
    return candidate


@contextmanager
def serve_chart(html_path):
    html = Path(html_path).read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url_path = urlsplit(self.path).path
            if url_path == "/chart.html":
                self._respond(html, "text/html; charset=utf-8")
                return
            vendor_file = _resolve_vendor_file(url_path)
            if vendor_file is not None:
                self._respond(vendor_file.read_bytes(), "application/javascript")
                return
            self.send_error(404)

        def _respond(self, body, content_type):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/chart.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
