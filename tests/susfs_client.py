#!/usr/bin/env python3
"""
HTTP client for the SUSFS_SUS_PATH remote test server.

Provides the same (rc, stdout, stderr) return shape as the original adb-based
wrappers so the host test can be refactored with minimal changes.

Uses urllib.request only — no third-party dependencies.
"""

import json
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8765"


def _post(path, payload, base_url=DEFAULT_BASE_URL, timeout=10):
    url = f"{base_url}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
        rc = exc.code
        try:
            return rc, "", body.decode("utf-8", errors="replace")
        except Exception:
            return rc, "", str(exc)

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return -1, "", body.decode("utf-8", errors="replace")

    return payload.get("rc", -1), payload.get("stdout", ""), payload.get("stderr", "")


def run_command(cmd, use_su=True, timeout=10, base_url=DEFAULT_BASE_URL):
    """Run a shell command on the device via the HTTP server."""
    return _post("/run", {"cmd": cmd, "use_su": use_su, "timeout": timeout},
                 base_url=base_url, timeout=timeout)


def run_ksusfs(args, use_su=True, timeout=10, base_url=DEFAULT_BASE_URL):
    """Run ksu_susfs <args> on the device via the HTTP server."""
    return _post("/run_susfs", {"args": args, "use_su": use_su, "timeout": timeout},
                 base_url=base_url, timeout=timeout)


def health(base_url=DEFAULT_BASE_URL, timeout=10):
    """Check the server is reachable. Returns True/False."""
    import urllib.request as _urlreq
    try:
        with _urlreq.urlopen(f"{base_url}/health", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False
