#!/usr/bin/env python3
"""
Test script for SUSFS_SPOOF_UNAME functionality.

Tests the SPOOF_UNAME sub-config of CONFIG_KSU_SUSFS by communicating with an
HTTP server running on the Termux device (uid >= 10000, root), which executes
ksu_susfs natively without the adb round-trip.

Tests:
1. Verify CONFIG_KSU_SUSFS_SPOOF_UNAME is enabled via show enabled_features
2. Set spoofed uname via ksu_susfs set_uname <release> <version> and verify rc=0
   NOTE: passing 'default' for either field uses the original kernel value.
3. Verify uname -r returns the spoofed release from Termux shell (non-root)
4. Verify uname -v returns the spoofed version from Termux shell (non-root)
5. Reset uname to default via ksu_susfs set_uname default default and verify rc=0
6. Verify uname -r returns the original kernel release after reset

Usage:
    python3 tests/test_susfs_spoof_uname.py --target-release 5.10.123-test --target-version "#1 SMP PREEMPT"
    python3 tests/test_susfs_spoof_uname.py --target-release 5.10.123-test --target-version "#1 SMP PREEMPT" --server-url http://127.0.0.1:8765

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
    """Test that CONFIG_KSU_SUSFS_SPOOF_UNAME is listed in enabled features."""
    print("=== Test: show enabled_features ===")
    rc, out, err = ksu_susfs("show enabled_features", use_su=use_su, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: ksu_susfs show enabled_features returned rc={rc}")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    if "CONFIG_KSU_SUSFS_SPOOF_UNAME" in out:
        print("  PASS: CONFIG_KSU_SUSFS_SPOOF_UNAME found in enabled features")
        print(f"  Output:\n{out}")
        return True
    else:
        print("  FAIL: CONFIG_KSU_SUSFS_SPOOF_UNAME NOT found in enabled features")
        print(f"  Output:\n{out}")
        return False


def test_set_uname(target_release, target_version, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Test setting spoofed uname via ksu_susfs set_uname."""
    print(f"\n=== Test: set_uname '{target_release}' '{target_version}' ===")
    rc, out, err = ksu_susfs(
        f"set_uname '{target_release}' '{target_version}'",
        use_su=use_su,
        base_url=base_url,
    )

    print(f"  rc={rc}")
    print(f"  stdout: {out}")
    if err:
        print(f"  stderr: {err}")

    if rc != 0:
        print(f"  FAIL: set_uname returned rc={rc}")
        print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

    ret_match = re.search(r"ret:\s*(-?\d+)", out)
    if ret_match:
        ret_val = int(ret_match.group(1))
        if ret_val == 0:
            print(f"  PASS: set_uname returned ret: {ret_val}")
            return True
        else:
            print(f"  FAIL: set_uname returned ret: {ret_val} (expected 0)")
            return False

    print("  PASS: set_uname command succeeded (rc=0)")
    return True


def test_uname_release_spoofed(target_release, base_url=DEFAULT_SERVER_URL):
    """Verify uname -r returns the spoofed release from Termux shell."""
    print(f"\n=== Test: uname -r returns spoofed release '{target_release}' ===")
    rc, out, err = adb_shell("uname -r", use_su=False, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: uname -r returned rc={rc}")
        print(f"  stderr: {err.strip() if err else '(none)'}")
        return False

    actual_release = out.strip()
    print(f"  uname -r: '{actual_release}'")
    print(f"  expected: '{target_release}'")

    if actual_release == target_release:
        print("  PASS: uname -r matches spoofed release")
        return True
    else:
        print(f"  FAIL: uname -r is '{actual_release}', expected '{target_release}'")
        return False


def test_uname_version_spoofed(target_version, base_url=DEFAULT_SERVER_URL):
    """Verify uname -v returns the spoofed version from Termux shell."""
    print(f"\n=== Test: uname -v returns spoofed version '{target_version}' ===")
    rc, out, err = adb_shell("uname -v", use_su=False, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: uname -v returned rc={rc}")
        print(f"  stderr: {err.strip() if err else '(none)'}")
        return False

    actual_version = out.strip()
    print(f"  uname -v: '{actual_version}'")
    print(f"  expected: '{target_version}'")

    if actual_version == target_version:
        print("  PASS: uname -v matches spoofed version")
        return True
    else:
        print(f"  FAIL: uname -v is '{actual_version}', expected '{target_version}'")
        return False


def test_reset_uname_to_default(base_url=DEFAULT_SERVER_URL):
    """Test resetting uname to default via ksu_susfs set_uname default default."""
    print(f"\n=== Test: set_uname default default ===")
    rc, out, err = ksu_susfs("set_uname default default", use_su=True, base_url=base_url)

    print(f"  rc={rc}")
    print(f"  stdout: {out}")
    if err:
        print(f"  stderr: {err}")

    if rc != 0:
        print(f"  FAIL: set_uname default default returned rc={rc}")
        print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

    ret_match = re.search(r"ret:\s*(-?\d+)", out)
    if ret_match:
        ret_val = int(ret_match.group(1))
        if ret_val == 0:
            print(f"  PASS: set_uname default default returned ret: {ret_val}")
            return True
        else:
            print(f"  FAIL: set_uname default default returned ret: {ret_val} (expected 0)")
            return False

    print("  PASS: set_uname default default command succeeded (rc=0)")
    return True


def test_uname_release_restored(original_release, base_url=DEFAULT_SERVER_URL):
    """Verify uname -r returns the original kernel release after reset."""
    print(f"\n=== Test: uname -r restored to original '{original_release}' ===")
    time.sleep(1)
    rc, out, err = adb_shell("uname -r", use_su=False, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: uname -r returned rc={rc}")
        print(f"  stderr: {err.strip() if err else '(none)'}")
        return False

    actual_release = out.strip()
    print(f"  uname -r: '{actual_release}'")
    print(f"  expected: '{original_release}'")

    if actual_release == original_release:
        print("  PASS: uname -r restored to original release")
        return True
    else:
        print(f"  FAIL: uname -r is '{actual_release}', expected '{original_release}'")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Test SUSFS_SPOOF_UNAME functionality via HTTP remote server"
    )
    parser.add_argument(
        "--target-release",
        required=True,
        help="Release string to spoof (e.g., 5.10.123-test)",
    )
    parser.add_argument(
        "--target-version",
        required=True,
        help="Version string to spoof (e.g., '#1 SMP PREEMPT')",
    )
    parser.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"Base URL of the remote server (default: {DEFAULT_SERVER_URL})",
    )

    args = parser.parse_args()

    target_release = args.target_release
    target_version = args.target_version
    base_url = args.server_url

    print("=" * 60)
    print("SUSFS_SPOOF_UNAME Test Suite")
    print("=" * 60)
    print(f"Target release: {target_release}")
    print(f"Target version: {target_version}")
    print(f"Server URL: {base_url}")
    print()

    if not check_server(base_url=base_url):
        sys.exit(1)

    # Capture original release/version before spoofing for restore verification
    rc_orig_r, out_orig_r, _ = adb_shell("uname -r", use_su=False, base_url=base_url)
    rc_orig_v, out_orig_v, _ = adb_shell("uname -v", use_su=False, base_url=base_url)
    original_release = out_orig_r.strip() if rc_orig_r == 0 else "unknown"
    original_version = out_orig_v.strip() if rc_orig_v == 0 else "unknown"
    print(f"Original release captured: '{original_release}'")
    print(f"Original version captured: '{original_version}'")
    print()

    results = []

    # Test 1: Check enabled features
    results.append(("show enabled_features", test_enabled_features(use_su=True, base_url=base_url)))

    # Test 2: Set spoofed uname
    results.append(("set_uname", test_set_uname(target_release, target_version, use_su=True, base_url=base_url)))

    # Small delay to ensure the change is applied
    time.sleep(1)

    # Test 3: Verify uname -r is spoofed
    results.append(("uname -r spoofed", test_uname_release_spoofed(target_release, base_url=base_url)))

    # Test 4: Verify uname -v is spoofed
    results.append(("uname -v spoofed", test_uname_version_spoofed(target_version, base_url=base_url)))

    # Test 5: Reset to default
    results.append(("set_uname default default", test_reset_uname_to_default(base_url=base_url)))

    # Small delay to ensure the reset is applied
    time.sleep(1)

    # Test 6: Verify original release restored
    results.append(("uname -r restored", test_uname_release_restored(original_release, base_url=base_url)))

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
