"""Serve the Chirp web viewer, or export it as static files for GitHub Pages.

python3 viewer.py                       # http://127.0.0.1:8000, reads logs/ live
python3 viewer.py --port 8080
python3 viewer.py --export docs --runs v1_20261028_101422   # static copy for GitHub Pages
python3 viewer.py --export docs --runs <run> --replace      # redo an earlier export

The frontend (viewer/, React) must be built once: cd viewer && npm install && npm run build.
During frontend work, `npm run dev` serves the UI with hot reload and forwards /api here.

Both modes serve the same paths, so the frontend can't tell them apart:
    api/runs.json                         list of runs
    api/run/<run>.json                    one run, without prompt text
    api/run/<run>/prompts/<agent>.json    one agent's system prompt + every user prompt and raw answer

Local only and read-only: binds to 127.0.0.1, answers GET/HEAD, and serves nothing outside
viewer/dist and the JSON built from logs/*.jsonl.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from loader import resolve
from viewer_data import build_run, list_runs

LOG_DIR = resolve("logs")
DIST = resolve("viewer/dist")
SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")
SECRET = re.compile(r"sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}")  # OpenAI / Google key shapes

_cache: dict = {}
_lock = threading.Lock()


def log_path(name: str):
    if not SAFE.match(name) or name.startswith("."):
        return None
    path = os.path.join(LOG_DIR, name + ".jsonl")
    return path if os.path.isfile(path) else None


def built(name: str):
    """(run, prompts) for a run, rebuilt only when the log file changes."""
    path = log_path(name)
    if path is None:
        return None
    mtime = os.path.getmtime(path)
    with _lock:
        hit = _cache.get(name)
        if hit and hit[0] == mtime:
            return hit[1]
    result = build_run(path)
    with _lock:
        _cache[name] = (mtime, result)
    return result


def api(path: str):
    """JSON-able answer for an api/... path, or None for 404."""
    parts = path.strip("/").split("/")
    if parts == ["api", "runs.json"]:
        return list_runs(LOG_DIR)
    if len(parts) == 3 and parts[:2] == ["api", "run"] and parts[2].endswith(".json"):
        b = built(parts[2][:-5])
        return b[0] if b else None
    if len(parts) == 5 and parts[:2] == ["api", "run"] and parts[3] == "prompts" and parts[4].endswith(".json"):
        b, agent = built(parts[2]), parts[4][:-5]
        if b and SAFE.match(agent):
            return b[1].get(agent)
    return None


NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Chirp viewer</title>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto;line-height:1.5">
<h1>The viewer isn't built yet</h1>
<p>Run this once, then reload:</p>
<pre>cd viewer
npm install
npm run build</pre>
<p>The data API already works: <a href="api/runs.json">api/runs.json</a></p></body>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "ChirpViewer"

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/"):
            data = api(path)
            if data is None:
                return self.send(404, b'{"error": "not found"}', "application/json", head)
            return self.send(200, json.dumps(data, separators=(",", ":")).encode(), "application/json", head)
        return self.static(path, head)

    def static(self, path, head):
        if not os.path.isdir(DIST):
            return self.send(200, NOT_BUILT.encode(), "text/html; charset=utf-8", head)
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        full = os.path.realpath(os.path.join(DIST, rel))
        if not full.startswith(os.path.realpath(DIST) + os.sep) or not os.path.isfile(full):
            return self.send(404, b"not found", "text/plain", head)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            self.send(200, f.read(), ctype, head)

    def send(self, code, body, ctype, head=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        if "--quiet" not in sys.argv:
            super().log_message(fmt, *args)


EXPORT_MARK = ".chirp-export"  # written into every export, so --replace only ever deletes an export


def export(out: str, runs: list, replace: bool = False):
    """Write the built frontend plus the JSON for `runs` as plain files (for GitHub Pages)."""
    if not os.path.isdir(DIST):
        raise SystemExit("Build the frontend first: cd viewer && npm install && npm run build")
    if os.path.exists(out) and os.listdir(out):
        if not replace:
            raise SystemExit(f"{out} exists and isn't empty. Add --replace to redo an earlier export there.")
        if not os.path.isfile(os.path.join(out, EXPORT_MARK)):
            raise SystemExit(f"{out} isn't an earlier Chirp export (no {EXPORT_MARK}); not touching it.")
    available = {r["name"]: r for r in list_runs(LOG_DIR)}
    missing = [r for r in runs if r not in available]
    if missing:
        raise SystemExit(f"No such run(s) in logs/: {', '.join(missing)}")
    files = {"api/runs.json": [available[r] for r in runs]}
    for name in runs:
        run, prompts = built(name)
        files[f"api/run/{name}.json"] = run
        for agent, p in prompts.items():
            files[f"api/run/{name}/prompts/{agent}.json"] = p
    texts = {}
    for rel, data in files.items():  # check everything before writing anything
        texts[rel] = json.dumps(data, separators=(",", ":"))
        if SECRET.search(texts[rel]):
            raise SystemExit(f"Refusing to export {rel}: it contains something shaped like an API key.")
    if os.path.exists(out) and os.listdir(out):
        shutil.rmtree(out)
    shutil.copytree(DIST, out)
    for rel, text in texts.items():
        full = os.path.join(out, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)
    open(os.path.join(out, ".nojekyll"), "w").close()  # GitHub Pages: serve files as-is
    with open(os.path.join(out, EXPORT_MARK), "w") as f:
        f.write("Made by: python3 viewer.py --export. Safe to delete and regenerate.\n")
    print(f"Exported {len(runs)} run(s), {len(files)} JSON files, to {out}/")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--export", metavar="DIR", help="write a static copy instead of serving")
    ap.add_argument("--runs", nargs="+", default=[], help="runs to export (names from logs/)")
    ap.add_argument("--replace", action="store_true", help="overwrite an earlier export in the same folder")
    ap.add_argument("--quiet", action="store_true", help="don't print each request")
    args = ap.parse_args(argv)
    if args.export:
        if not args.runs:
            raise SystemExit("Name the runs to export, e.g. --runs v1_20261028_101422")
        return export(args.export, args.runs, args.replace)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        raise SystemExit(f"Can't use port {args.port} ({e.strerror}). Try another: python3 viewer.py --port 8001")
    print(f"Chirp viewer on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
