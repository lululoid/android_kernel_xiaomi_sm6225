#!/usr/bin/env python3
"""
Test script for SUSFS_SUS_KSTAT functionality.

Tests the SUS_KSTAT sub-config of CONFIG_KSU_SUSFS by communicating with an
HTTP server running on the Termux device (uid >= 10000, root), which executes
ksu_susfs natively without the adb round-trip.

Tests:
1. Verify CONFIG_KSU_SUSFS_SUS_KSTAT is enabled via show enabled_features
2. Create a test file on the device
3. Capture original stat output before spoofing (informational)
4. Set spoofed kstat via ksu_susfs add_sus_kstat <path> and verify rc=0
   NOTE: add_sus_kstat dynamically clones current file stats
5. Verify stat runs without error from Termux shell
   NOTE: SUSFS_SUS_KSTAT spoofing requires TIF_PROC_UMOUNTED which is set on
   zygote-spawned app processes, not on shells. From a plain shell, stat will
   return real values even after spoofing is configured.
6. Update spoofed kstat via ksu_susfs update_sus_kstat and verify rc=0
7. Cleanup: remove test file

Usage:
    python3 tests/test_susfs_sus_kstat.py \\
        --target-path /sdcard/susfs_kstat_test
    python3 tests/test_susfs_sus_kstat.py \\
        --target-path /sdcard/susfs_kstat_test \\
        --server-url http://127.0.0.1:8765

Setup (run once on the Termux device before testing):
    python3 tests/susfs_server.py
    # From the host:
    adb forward tcp:8765 tcp:8765
"""

import argparse
import sys
import time

from susfs_client import run_command, run_ksusfs, health

KSUSFS = "/data/adb/ksu/bin/ksu_susfs"
DEFAULT_SERVER_URL = "http://127.0.0.1:8765"


def adb_shell(command, use_su=False, timeout=10, base_url=DEFAULT_SERVER_URL):
    """Run a shell command via the remote HTTP server.

    Args:
        command: The command string to execute on the device.
        use_su: If True, wrap command with 'sudo'.
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
        use_su: If True, run via 'sudo'.
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
    """Test that CONFIG_KSU_SUSFS_SUS_KSTAT is listed in enabled features."""
    print("=== Test: show enabled_features ===")
    rc, out, err = ksu_susfs("show enabled_features", use_su=use_su, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: ksu_susfs show enabled_features returned rc={rc}")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    if "CONFIG_KSU_SUSFS_SUS_KSTAT" in out:
        print("  PASS: CONFIG_KSU_SUSFS_SUS_KSTAT found in enabled features")
        print(f"  Output:\n{out}")
        return True
    else:
        print("  FAIL: CONFIG_KSU_SUSFS_SUS_KSTAT NOT found in enabled features")
        print(f"  Output:\n{out}")
        return False


def test_create_test_file(target_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Write a test file on the device."""
    print(f"\n=== Test: create test file '{target_path}' ===")
    cmd = f"echo 'susfs_kstat_test_content' > {target_path}"
    rc, out, err = adb_shell(cmd, use_su=use_su, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: Failed to create test file (rc={rc})")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    # Verify the file was created correctly
    rc, out, err = adb_shell(f"cat {target_path}", use_su=use_su, base_url=base_url)
    if rc != 0:
        print(f"  FAIL: Cannot read back test file (rc={rc})")
        print(f"  stderr: {err}")
        return False

    actual = out.strip()
    if actual != "susfs_kstat_test_content":
        print(f"  FAIL: Test file content mismatch")
        print(f"  actual:   '{actual}'")
        print(f"  expected: 'susfs_kstat_test_content'")
        return False

    print(f"  PASS: Test file created with content '{actual}'")
    return True


def test_capture_original_stat(target_path, base_url=DEFAULT_SERVER_URL):
    """Capture original stat output before spoofing for reference."""
    print(f"\n=== Test: capture original stat for '{target_path}' ===")
    rc, out, err = adb_shell(f"stat {target_path}", use_su=False, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: stat returned rc={rc}")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    print(f"  Original stat:\n{out}")
    return True


def test_add_sus_kstat(target_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Test setting spoofed kstat via ksu_susfs add_sus_kstat <path>.

    add_sus_kstat dynamically clones current file stats and marks them for
    spoofing. Returns rc=0 on success.
    """
    print(f"\n=== Test: add_sus_kstat '{target_path}' ===")
    rc, out, err = ksu_susfs(f"add_sus_kstat {target_path}", use_su=use_su,
                             base_url=base_url)

    print(f"  rc={rc}")
    print(f"  stdout: {out}")
    if err:
        print(f"  stderr: {err}")

    if rc != 0:
        print(f"  FAIL: add_sus_kstat returned rc={rc}")
        print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

    ret_match = __import__('re').search(r"ret:\s*(-?\d+)", out)
    if ret_match:
        ret_val = int(ret_match.group(1))
        if ret_val == 0:
            print(f"  PASS: add_sus_kstat returned ret: {ret_val}")
            return True
        else:
            print(f"  FAIL: add_sus_kstat returned ret: {ret_val} (expected 0)")
            return False

    print("  PASS: add_sus_kstat command succeeded (rc=0)")
    return True


def test_stat_runs(target_path, base_url=DEFAULT_SERVER_URL):
    """Verify stat runs without error from Termux shell.

    NOTE: SUSFS_SUS_KSTAT spoofing requires TIF_PROC_UMOUNTED which is set on
    zygote-spawned app processes, not on shells. From a plain shell, stat will
    return real values even after spoofing is configured. This test verifies
    stat runs without error (informational).
    """
    print(f"\n=== Test: stat runs from Termux shell (informational) ===")
    rc, out, err = adb_shell(f"stat {target_path}", use_su=False, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: stat returned rc={rc}")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    print(f"  stat output:\n{out}")
    print("  INFO: From a plain shell (no TIF_PROC_UMOUNTED), stat returns real values.")
    print("  Spoofed values are visible only from umounted app processes.")
    return True


def test_update_sus_kstat(target_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Test updating spoofed kstat via ksu_susfs update_sus_kstat."""
    print(f"\n=== Test: update_sus_kstat '{target_path}' ===")
    rc, out, err = ksu_susfs(f"update_sus_kstat {target_path}", use_su=use_su,
                             base_url=base_url)

    print(f"  rc={rc}")
    print(f"  stdout: {out}")
    if err:
        print(f"  stderr: {err}")

    if rc != 0:
        print(f"  FAIL: update_sus_kstat returned rc={rc}")
        print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

    ret_match = __import__('re').search(r"ret:\s*(-?\d+)", out)
    if ret_match:
        ret_val = int(ret_match.group(1))
        if ret_val == 0:
            print(f"  PASS: update_sus_kstat returned ret: {ret_val}")
            return True
        else:
            print(f"  FAIL: update_sus_kstat returned ret: {ret_val} (expected 0)")
            return False

    print("  PASS: update_sus_kstat command succeeded (rc=0)")
    return True


def test_cleanup(target_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Remove test file."""
    print(f"\n=== Cleanup: remove {target_path} ===")
    rc, out, err = adb_shell(f"rm -f {target_path}", use_su=use_su, base_url=base_url)
    if rc == 0:
        print(f"  PASS: Cleanup succeeded")
    else:
        print(f"  INFO: Cleanup returned rc={rc}")
        print(f"  stderr: {err.strip() if err else '(none)'}")


def main():
    parser = argparse.ArgumentParser(
        description="Test SUSFS_SUS_KSTAT functionality via HTTP remote server"
    )
    parser.add_argument(
        "--target-path",
        required=True,
        help="Target path to spoof kstat for (e.g., /sdcard/susfs_kstat_test)",
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
    print("SUSFS_SUS_KSTAT Test Suite")
    print("=" * 60)
    print(f"Target path: {target_path}")
    print(f"Server URL: {base_url}")
    print()

    if not check_server(base_url=base_url):
        sys.exit(1)

    results = []

    # Test 1: Check enabled features
    results.append(("show enabled_features", test_enabled_features(use_su=True, base_url=base_url)))

    # Test 2: Create test file
    results.append(("create test file",
                    test_create_test_file(target_path, use_su=True, base_url=base_url)))

    # Test 3: Capture original stat (informational)
    results.append(("capture original stat",
                    test_capture_original_stat(target_path, base_url=base_url)))

    # Small delay to ensure file is fully written
    time.sleep(1)

    # Test 4: Set spoofed kstat
    results.append(("add_sus_kstat",
                    test_add_sus_kstat(target_path, use_su=True, base_url=base_url)))

    # Small delay to ensure the change is applied
    time.sleep(1)

    # Test 5: Verify stat runs from shell (informational)
    results.append(("stat runs from shell",
                    test_stat_runs(target_path, base_url=base_url)))

    # Test 6: Update spoofed kstat
    results.append(("update_sus_kstat",
                    test_update_sus_kstat(target_path, use_su=True, base_url=base_url)))

    # Cleanup
    test_cleanup(target_path, use_su=True, base_url=base_url)

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
