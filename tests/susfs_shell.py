#!/usr/bin/env python3
"""
Send a shell command through the SUSFS test server to the Termux shell.

Usage:
    python3 tests/susfs_shell.py "ls -la /data/local/tmp"
    python3 tests/susfs_shell.py --use-su "su 2000 id"
    python3 tests/susfs_shell.py --server-url http://127.0.0.1:8765 "id"
"""

import argparse
import sys

from susfs_client import run_command


def main():
    parser = argparse.ArgumentParser(
        description="Send a shell command through the SUSFS test server to Termux"
    )
    parser.add_argument(
        "command",
        help="Shell command to execute on the device",
    )
    parser.add_argument(
        "--use-su",
        action="store_true",
        default=False,
        help="Wrap command with 'su -c' (run as root)",
    )
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8765",
        help="Base URL of the remote server (default: http://127.0.0.1:8765)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Command timeout in seconds (default: 10)",
    )

    args = parser.parse_args()

    rc, out, err = run_command(
        args.command,
        use_su=args.use_su,
        timeout=args.timeout,
        base_url=args.server_url,
    )

    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)

    sys.exit(rc)


if __name__ == "__main__":
    main()
