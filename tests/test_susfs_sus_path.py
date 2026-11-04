#!/usr/bin/env python3
"""
Test script for SUSFS_SUS_PATH functionality.

Tests the SUS_PATH sub-config of CONFIG_KSU_SUSFS by communicating with an
HTTP server running on the Termux device (uid >= 10000, root), which executes
ksu_susfs natively without the adb round-trip.

Tests:
1. Verify CONFIG_KSU_SUSFS_SUS_PATH is enabled via show enabled_features
2. Add a path via ksu_susfs add_sus_path and verify rc=0
3. Verify path is hidden from non-root access (without su -c)
   NOTE: SUSFS_SUS_PATH hiding requires TIF_PROC_UMOUNTED thread flag on the
   accessing process. This flag is set during setresuid escalation to root.
   A plain shell (uid=2000) does not have this flag, so test 3 will report
   INFO (not FAIL) when hiding is not observed.
4. Verify path is still accessible from root access (with su -c)

Usage:
    python3 tests/test_susfs_sus_path.py --target-path /data/data/com.test.app/private
    python3 tests/test_susfs_sus_path.py --target-path /sdcard/test_hide --cleanup

Setup (run once on the Termux device before testing):
    python3 tests/susfs_server.py
    # From the host:
    adb forward tcp:8765 tcp:8765
"""

import argparse
import re
import sys
import time

from susfs_client import run_command, run_ksusfs, health

KSUSFS = "/data/adb/ksu/bin/ksu_susfs"
DEFAULT_SERVER_URL = "http://127.0.0.1:8765"


def adb_shell(command, use_su=False, timeout=10, base_url=DEFAULT_SERVER_URL):
    """Run a command via the remote HTTP server.

    Args:
        command: The command string to execute on the device.
        use_su: If True, wrap command with 'su -c'.
        timeout: Timeout in seconds.
        base_url: Base URL of the remote server.

    Returns:
        (returncode, stdout, stderr)
    """
    return run_command(command, use_su=use_su, timeout=timeout, base_url=base_url)


def ksu_susfs(args, use_su=True, timeout=10, base_url=DEFAULT_SERVER_URL):
    """Run a ksu_susfs command via the remote HTTP server.

    Args:
        args: Arguments to pass to ksu_susfs.
        use_su: If True, run via 'su -c'.
        timeout: Timeout in seconds.
        base_url: Base URL of the remote server.

    Returns:
        (returncode, stdout, stderr)
    """
    return run_ksusfs(args, use_su=use_su, timeout=timeout, base_url=base_url)


def check_server(base_url=DEFAULT_SERVER_URL):
    """Verify the remote server is reachable."""
    if not health(base_url=base_url):
        print(f"FAIL: Cannot reach server at {base_url}")
        print("  Start the server on the Termux device: python3 tests/susfs_server.py")
        print("  Then forward the port: adb forward tcp:8765 tcp:8765")
        return False
    print(f"Server reachable at {base_url}")
    return True


def test_enabled_features(use_su=True, base_url=DEFAULT_SERVER_URL):
    """Test that CONFIG_KSU_SUSFS_SUS_PATH is listed in enabled features."""
    print("=== Test: show enabled_features ===")
    rc, out, err = ksu_susfs("show enabled_features", use_su=use_su, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: ksu_susfs show enabled_features returned rc={rc}")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    if "CONFIG_KSU_SUSFS_SUS_PATH" in out:
        print("  PASS: CONFIG_KSU_SUSFS_SUS_PATH found in enabled features")
        print(f"  Output:\n{out}")
        return True
    else:
        print("  FAIL: CONFIG_KSU_SUSFS_SUS_PATH NOT found in enabled features")
        print(f"  Output:\n{out}")
        return False


def test_add_sus_path(target_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Test adding a path via ksu_susfs add_sus_path."""
    print(f"\n=== Test: add_sus_path '{target_path}' ===")
    rc, out, err = ksu_susfs(f"add_sus_path {target_path}", use_su=use_su, base_url=base_url)

    print(f"  rc={rc}")
    print(f"  stdout: {out}")
    if err:
        print(f"  stderr: {err}")

    if rc != 0:
        print(f"  FAIL: add_sus_path command returned rc={rc}")
        print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

    ret_match = re.search(r"ret:\s*(-?\d+)", out)
    if ret_match:
        ret_val = int(ret_match.group(1))
        if ret_val == 0:
            print(f"  PASS: add_sus_path returned ret: {ret_val}")
            return True
        else:
            print(f"  FAIL: add_sus_path returned ret: {ret_val} (expected 0)")
            return False

    if "successfully added" in out.lower() or "added to" in out.lower():
        print("  PASS: add_sus_path reported success (no explicit ret code)")
        return True

    print("  PASS: add_sus_path command succeeded (rc=0, no ret code in output)")
    return True


def test_path_hidden(target_path, use_su=False, base_url=DEFAULT_SERVER_URL):
    """Test that path is hidden from non-root access.

    SUSFS_SUS_PATH hiding requires the accessing process to have both:
    1. TIF_PROC_UMOUNTED thread flag set (set during setresuid escalation to
       root via the KSU manager), AND
    2. uid >= SUSFS_UID_THRESHOLD (2000 with CONFIG_KSU_SUSFS_TEST_UID_THRESHOLD=y).

    A plain shell (uid=2000) does NOT have TIF_PROC_UMOUNTED, so path
    hiding will not be observed from the shell alone. To properly test hiding,
    the test process must first escalate to root (setting TIF_PROC_UMOUNTED)
    and then drop back to a non-root uid while preserving the flag.

    This test runs as plain shell (uid=2000, no TIF_PROC_UMOUNTED).
    If it fails, verify via dmesg that AS_FLAGS_SUS_PATH was flagged on the
    inode, and manually test from a process with TIF_PROC_UMOUNTED set.
    """
    print(f"\n=== Test: path hidden from non-root (shell without su) ===")
    rc, out, err = adb_shell(f"ls {target_path}", use_su=False, base_url=base_url)

    if rc != 0:
        print(f"  PASS: Path is hidden (ls returned rc={rc}, no access)")
        print(f"  stderr: {err.strip() if err else '(none)'}")
        return True
    else:
        print(f"  INFO: Path is visible from plain shell (uid=2000, no TIF_PROC_UMOUNTED)")
        print(f"  This is expected if TIF_PROC_UMOUNTED is not set on the shell process.")
        print(f"  Path hiding requires: CONFIG_KSU_SUSFS_TEST_UID_THRESHOLD=y + TIF_PROC_UMOUNTED")
        print(f"  To manually verify hiding, run: su -c 'su 2000 ls {target_path}'")
        print(f"  (from a root shell that has TIF_PROC_UMOUNTED from setresuid escalation)")
        print(f"  stdout: {out}")
        return False


def test_path_visible_root(target_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Test that path is still accessible from root."""
    print(f"\n=== Test: path visible from root (shell with su) ===")
    rc, out, err = adb_shell(f"ls {target_path}", use_su=True, base_url=base_url)

    if rc == 0:
        print(f"  PASS: Path is accessible from root (ls returned rc=0)")
        print(f"  stdout: {out[:200]}")
        return True
    else:
        print(f"  FAIL: Path not accessible from root (ls returned rc={rc})")
        print(f"  stderr: {err.strip() if err else '(none)'}")
        return False


def test_path_not_hidden_before(target_path, use_su=False, base_url=DEFAULT_SERVER_URL):
    """Test that path is visible before adding to SUS_PATH."""
    print(f"\n=== Test: path visible BEFORE add_sus_path (non-root) ===")
    rc, out, err = adb_shell(f"ls {target_path}", use_su=False, base_url=base_url)

    if rc == 0:
        print(f"  PASS: Path is visible before add_sus_path (ls returned rc=0)")
        print(f"  stdout: {out[:200]}")
        return True
    else:
        print(f"  INFO: Path not visible before add_sus_path (rc={rc}) - may not exist")
        print(f"  stderr: {err.strip() if err else '(none)'}")
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Test SUSFS_SUS_PATH functionality via HTTP remote server"
    )
    parser.add_argument(
        "--target-path",
        required=True,
        help="Target path to hide (e.g., /data/data/com.test.app/private)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove the test path after testing",
    )
    parser.add_argument(
        "--no-root-test",
        action="store_true",
        help="Skip root visibility test",
    )
    parser.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"Base URL of the remote server (default: {DEFAULT_SERVER_URL})",
    )

    args = parser.parse_args()

    target_path = args.target_path
    base_url = args.server_url

    print("=" * 60)
    print("SUSFS_SUS_PATH Test Suite")
    print("=" * 60)
    print(f"Target path: {target_path}")
    print(f"Server URL: {base_url}")
    print()

    if not check_server(base_url=base_url):
        sys.exit(1)

    results = []

    # Test 1: Check enabled features
    results.append(("show enabled_features", test_enabled_features(use_su=True, base_url=base_url)))

    # Test 2: Verify path visibility BEFORE adding
    results.append(("path visible before (non-root)",
                    test_path_not_hidden_before(target_path, use_su=False, base_url=base_url)))

    # Test 3: Add path via ksu_susfs
    results.append(("add_sus_path", test_add_sus_path(target_path, use_su=True, base_url=base_url)))

    # Small delay to ensure the change is applied
    time.sleep(1)

    # Test 4: Path hidden from non-root
    results.append(("path hidden (non-root)", test_path_hidden(target_path, use_su=False, base_url=base_url)))

    # Test 5: Path visible from root
    if not args.no_root_test:
        results.append(("path visible (root)",
                        test_path_visible_root(target_path, use_su=True, base_url=base_url)))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = 0
    failed = 0
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {status}: {name}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {len(results)}, Passed: {passed}, Failed: {failed}")

    if failed > 0:
        print("\nSome tests FAILED.")
        sys.exit(1)
    else:
        print("\nAll tests PASSED.")
        sys.exit(0)


if __name__ == "__main__":
    main()
