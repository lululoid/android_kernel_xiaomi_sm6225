#!/usr/bin/env python3
"""
SUSFS_SUS_PATH remote test server.

Runs on the Termux device (uid >= 10000, root) and exposes an HTTP endpoint
so a host machine can execute `ksu_susfs` commands without the adb round-trip.

Bind to 127.0.0.1 only; reach from the host via `adb forward tcp:8765 tcp:8765`.

Endpoints:
    GET  /health            -> {"ok": true}
    POST /run               -> body {"cmd": "...", "use_su": bool}
    POST /run_susfs         -> body {"args": "...", "use_su": bool}

Responses are JSON: {"rc": int, "stdout": str, "stderr": str}.
"""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8765
KSUSFS = "/data/adb/ksu/bin/ksu_susfs"


def run_command(cmd, use_su=True, timeout=10):
    """Run a shell command on the device, optionally wrapped in sudo."""
    if use_su:
        full_cmd = f"sudo {cmd}"
    else:
        full_cmd = cmd

    result = subprocess.run(
        full_cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def run_ksusfs(args, use_su=True, timeout=10):
    """Run ksu_susfs <args> on the device."""
    return run_command(f"{KSUSFS} {args}", use_su=use_su, timeout=timeout)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = json.loads(self._read_body() or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return

        use_su = body.get("use_su", True)
        timeout = body.get("timeout", 10)

        if self.path == "/run":
            cmd = body.get("cmd", "")
            if not cmd:
                self._send_json(400, {"error": "cmd is required"})
                return
            rc, out, err = run_command(cmd, use_su=use_su, timeout=timeout)
            self._send_json(200, {"rc": rc, "stdout": out, "stderr": err})

        elif self.path == "/run_susfs":
            args = body.get("args", "")
            if not args:
                self._send_json(400, {"error": "args is required"})
                return
            rc, out, err = run_ksusfs(args, use_su=use_su, timeout=timeout)
            self._send_json(200, {"rc": rc, "stdout": out, "stderr": err})

        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        pass


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"SUSFS test server listening on {HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
