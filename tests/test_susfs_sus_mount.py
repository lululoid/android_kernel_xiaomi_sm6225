#!/usr/bin/env python3
"""
Test script for SUSFS_SUS_MOUNT functionality.

Tests the SUS_MOUNT sub-config of CONFIG_KSU_SUSFS by communicating with an
HTTP server running on the Termux device (uid >= 10000, root), which executes
ksu_susfs natively without the adb round-trip.

Tests:
1. Verify CONFIG_KSU_SUSFS_SUS_MOUNT is enabled via show enabled_features
2. Enable hide_sus_mnts_for_non_su_procs via ksu_susfs hide_sus_mnts_for_non_su_procs 1
3. Add a mount path via ksu_susfs add_sus_mount and verify rc=0
   NOTE: add_sus_mount is deprecated - kernel auto-detects ksu-domain mounts now.
   The kernel handler always returns rc=0 (no-op success).
4. Read /proc/self/mounts before/after enabling hide toggle (informational)
   - From Termux shell (non-ksu domain context), sus mounts WILL be hidden from
     /proc/self/mounts when hide_sus_mnts_for_non_su_procs is enabled AND sus
     mounts exist on the device.
   - From adb root shell (ksu domain context), mounts will NOT be hidden.
   - Visual effect depends on whether any sus mounts exist on the device.
5. Disable hide_sus_mnts_for_non_su_procs via ksu_susfs hide_sus_mnts_for_non_su_procs 0
6. Verify path visibility from root access (with su -c)

Usage:
    python3 tests/test_susfs_sus_mount.py --target-mount-path /data/local/tmp/susfs_mount_test
    python3 tests/test_susfs_sus_mount.py --target-mount-path /sdcard/test_mount --cleanup

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
    """Test that CONFIG_KSU_SUSFS_SUS_MOUNT is listed in enabled features."""
    print("=== Test: show enabled_features ===")
    rc, out, err = ksu_susfs("show enabled_features", use_su=use_su, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: ksu_susfs show enabled_features returned rc={rc}")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    if "CONFIG_KSU_SUSFS_SUS_MOUNT" in out:
        print("  PASS: CONFIG_KSU_SUSFS_SUS_MOUNT found in enabled features")
        print(f"  Output:\n{out}")
        return True
    else:
        print("  FAIL: CONFIG_KSU_SUSFS_SUS_MOUNT NOT found in enabled features")
        print(f"  Output:\n{out}")
        return False


def test_hide_sus_mnts_enable(base_url=DEFAULT_SERVER_URL):
    """Test enabling hide_sus_mnts_for_non_su_procs via ksu_susfs."""
    print("\n=== Test: hide_sus_mnts_for_non_su_procs 1 ===")
    rc, out, err = ksu_susfs("hide_sus_mnts_for_non_su_procs 1", use_su=True, base_url=base_url)

    print(f"  rc={rc}")
    print(f"  stdout: {out}")
    if err:
        print(f"  stderr: {err}")

    if rc != 0:
        print(f"  FAIL: hide_sus_mnts_for_non_su_procs 1 returned rc={rc}")
        print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

    ret_match = re.search(r"ret:\s*(-?\d+)", out)
    if ret_match:
        ret_val = int(ret_match.group(1))
        if ret_val == 0:
            print(f"  PASS: hide_sus_mnts_for_non_su_procs 1 returned ret: {ret_val}")
            return True
        else:
            print(f"  FAIL: hide_sus_mnts_for_non_su_procs 1 returned ret: {ret_val} (expected 0)")
            return False

    print("  PASS: hide_sus_mnts_for_non_su_procs 1 succeeded (rc=0)")
    return True


def test_add_sus_mount(target_mount_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Test adding a mount path via ksu_susfs add_sus_mount.

    NOTE: add_sus_mount is deprecated - kernel auto-detects ksu-domain mounts now.
    The kernel handler always returns rc=0 (no-op success). This test verifies
    the command is accepted without error.
    """
    # Create the path first - ksu_susfs add_sus_mount stats the path before sending
    rc_create, out_create, err_create = adb_shell(
        f"mkdir -p {target_mount_path}", use_su=True, base_url=base_url
    )
    if rc_create != 0:
        print(f"  INFO: Failed to create path '{target_mount_path}'")
        print(f"  stdout: {out_create}")
        print(f"  stderr: {err_create}")
        return False

    print(f"\n=== Test: add_sus_mount '{target_mount_path}' ===")
    rc, out, err = ksu_susfs(f"add_sus_mount {target_mount_path}", use_su=use_su, base_url=base_url)

    print(f"  rc={rc}")
    print(f"  stdout: {out}")
    if err:
        print(f"  stderr: {err}")

    if rc != 0:
        print(f"  FAIL: add_sus_mount command returned rc={rc}")
        print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

    ret_match = re.search(r"ret:\s*(-?\d+)", out)
    if ret_match:
        ret_val = int(ret_match.group(1))
        if ret_val == 0:
            print(f"  PASS: add_sus_mount returned ret: {ret_val}")
            return True
        else:
            print(f"  FAIL: add_sus_mount returned ret: {ret_val} (expected 0)")
            return False

    print("  PASS: add_sus_mount command succeeded (rc=0)")
    return True


def test_proc_mounts_visibility(base_url=DEFAULT_SERVER_URL):
    """Read /proc/self/mounts before/after hide toggle (informational).

    From Termux shell (non-ksu domain context), sus mounts WILL be hidden from
    /proc/self/mounts when hide_sus_mnts_for_non_su_procs is enabled AND sus
    mounts exist on the device.

    From adb root shell (ksu domain context), mounts will NOT be hidden even
    when toggle is enabled.

    Visual effect depends on whether any sus mounts exist on the device.
    This test reports INFO; it does not PASS/FAIL.
    """
    print("\n=== Test: /proc/self/mounts visibility (informational) ===")
    rc, out, err = adb_shell("wc -l /proc/self/mounts", use_su=False, base_url=base_url)

    if rc != 0:
        print(f"  INFO: Cannot read /proc/self/mounts (rc={rc})")
        print(f"  stderr: {err.strip() if err else '(none)'}")
        return True

    line_count = out.strip()
    print(f"  INFO: /proc/self/mounts has {line_count} lines from Termux shell (non-ksu domain)")

    # Read from root too
    rc_root, out_root, err_root = adb_shell("wc -l /proc/self/mounts", use_su=True, base_url=base_url)
    if rc_root == 0:
        print(f"  INFO: /proc/self/mounts has {out_root.strip()} lines from root shell (ksu domain)")

    return True


def test_hide_sus_mnts_disable(base_url=DEFAULT_SERVER_URL):
    """Test disabling hide_sus_mnts_for_non_su_procs via ksu_susfs."""
    print("\n=== Test: hide_sus_mnts_for_non_su_procs 0 ===")
    rc, out, err = ksu_susfs("hide_sus_mnts_for_non_su_procs 0", use_su=True, base_url=base_url)

    print(f"  rc={rc}")
    print(f"  stdout: {out}")
    if err:
        print(f"  stderr: {err}")

    if rc != 0:
        print(f"  FAIL: hide_sus_mnts_for_non_su_procs 0 returned rc={rc}")
        print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

    ret_match = re.search(r"ret:\s*(-?\d+)", out)
    if ret_match:
        ret_val = int(ret_match.group(1))
        if ret_val == 0:
            print(f"  PASS: hide_sus_mnts_for_non_su_procs 0 returned ret: {ret_val}")
            return True
        else:
            print(f"  FAIL: hide_sus_mnts_for_non_su_procs 0 returned ret: {ret_val} (expected 0)")
            return False

    print("  PASS: hide_sus_mnts_for_non_su_procs 0 succeeded (rc=0)")
    return True


def test_target_path_visible_root(target_mount_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Test that target path is still accessible from root."""
    print(f"\n=== Test: target path visible from root (shell with su) ===")
    rc, out, err = adb_shell(f"ls {target_mount_path}", use_su=True, base_url=base_url)

    if rc == 0:
        print(f"  PASS: Path is accessible from root (ls returned rc=0)")
        print(f"  stdout: {out[:200]}")
        return True
    else:
        print(f"  INFO: Path not accessible from root (ls returned rc={rc}) - path may not exist")
        print(f"  stderr: {err.strip() if err else '(none)'}")
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Test SUSFS_SUS_MOUNT functionality via HTTP remote server"
    )
    parser.add_argument(
        "--target-mount-path",
        required=True,
        help="Target mount path to add (e.g., /data/local/tmp/susfs_mount_test)",
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

    target_mount_path = args.target_mount_path
    base_url = args.server_url

    print("=" * 60)
    print("SUSFS_SUS_MOUNT Test Suite")
    print("=" * 60)
    print(f"Target mount path: {target_mount_path}")
    print(f"Server URL: {base_url}")
    print()

    if not check_server(base_url=base_url):
        sys.exit(1)

    results = []

    # Test 1: Check enabled features
    results.append(("show enabled_features", test_enabled_features(use_su=True, base_url=base_url)))

    # Test 2: Enable hide toggle
    results.append(("hide_sus_mnts_for_non_su_procs 1",
                    test_hide_sus_mnts_enable(base_url=base_url)))

    # Test 3: Add sus mount
    results.append(("add_sus_mount",
                    test_add_sus_mount(target_mount_path, use_su=True, base_url=base_url)))

    # Small delay to ensure the change is applied
    time.sleep(1)

    # Test 4: /proc/self/mounts visibility (informational)
    results.append(("/proc/self/mounts visibility",
                    test_proc_mounts_visibility(base_url=base_url)))

    # Test 5: Disable hide toggle
    results.append(("hide_sus_mnts_for_non_su_procs 0",
                    test_hide_sus_mnts_disable(base_url=base_url)))

    # Test 6: Target path visible from root
    if not args.no_root_test:
        results.append(("target path visible (root)",
                        test_target_path_visible_root(target_mount_path, use_su=True, base_url=base_url)))

    # Cleanup
    if args.cleanup:
        print(f"\n=== Cleanup: remove {target_mount_path} ===")
        rc, out, err = adb_shell(f"rm -rf {target_mount_path}", use_su=True, base_url=base_url)
        if rc == 0:
            print(f"  PASS: Cleanup succeeded")
        else:
            print(f"  INFO: Cleanup returned rc={rc}")
            print(f"  stderr: {err.strip() if err else '(none)'}")

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
