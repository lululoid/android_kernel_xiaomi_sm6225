#!/usr/bin/env python3
"""
Test script for SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG functionality.

Tests the SPOOF_CMDLINE_OR_BOOTCONFIG sub-config of CONFIG_KSU_SUSFS by
communicating with an HTTP server running on the Termux device (uid >= 10000,
root), which executes ksu_susfs natively without the adb round-trip.

Tests:
1. Verify CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG is enabled via show
   enabled_features
2. Capture original /proc/cmdline content before spoofing
3. Write a spoofed cmdline test file on the device
4. Set spoofed cmdline via ksu_susfs set_cmdline_or_bootconfig <file> and
   verify rc=0
5. Verify /proc/cmdline contains the spoofed content from Termux shell
6. Restore original /proc/cmdline by setting it back via ksu_susfs
   set_cmdline_or_bootconfig with original content file
7. Verify /proc/cmdline returns to original content

Usage:
    python3 tests/test_susfs_spoof_cmdline_or_bootconfig.py \\
        --target-cmdline "console=tty0 susfs_test" \\
        --test-file-path /data/local/tmp/fake_cmdline
    python3 tests/test_susfs_spoof_cmdline_or_bootconfig.py \\
        --target-cmdline "console=tty0 susfs_test" \\
        --test-file-path /data/local/tmp/fake_cmdline \\
        --server-url http://127.0.0.1:8765

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
    """Test that CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG is listed in enabled features."""
    print("=== Test: show enabled_features ===")
    rc, out, err = ksu_susfs("show enabled_features", use_su=use_su, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: ksu_susfs show enabled_features returned rc={rc}")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    if "CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG" in out:
        print("  PASS: CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG found in enabled features")
        print(f"  Output:\n{out}")
        return True
    else:
        print("  FAIL: CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG NOT found in enabled features")
        print(f"  Output:\n{out}")
        return False


def test_create_test_file(target_file_path, target_cmdline, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Write a spoofed cmdline test file on the device."""
    print(f"\n=== Test: create test file '{target_file_path}' ===")
    cmd = f"printf '%s' '{target_cmdline}' > {target_file_path}"
    rc, out, err = adb_shell(cmd, use_su=use_su, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: Failed to create test file (rc={rc})")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    # Verify the file was created correctly
    rc, out, err = adb_shell(f"cat {target_file_path}", use_su=use_su, base_url=base_url)
    if rc != 0:
        print(f"  FAIL: Cannot read back test file (rc={rc})")
        print(f"  stderr: {err}")
        return False

    actual = out.strip()
    if actual != target_cmdline:
        print(f"  FAIL: Test file content mismatch")
        print(f"  actual:   '{actual}'")
        print(f"  expected: '{target_cmdline}'")
        return False

    print(f"  PASS: Test file created with content '{actual}'")
    return True


def test_set_cmdline_or_bootconfig(target_file_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Test setting spoofed cmdline via ksu_susfs set_cmdline_or_bootconfig."""
    print(f"\n=== Test: set_cmdline_or_bootconfig '{target_file_path}' ===")
    rc, out, err = ksu_susfs(
        f"set_cmdline_or_bootconfig {target_file_path}",
        use_su=use_su,
        base_url=base_url,
    )

    print(f"  rc={rc}")
    print(f"  stdout: {out}")
    if err:
        print(f"  stderr: {err}")

    if rc != 0:
        print(f"  FAIL: set_cmdline_or_bootconfig returned rc={rc}")
        print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

    ret_match = re.search(r"ret:\s*(-?\d+)", out)
    if ret_match:
        ret_val = int(ret_match.group(1))
        if ret_val == 0:
            print(f"  PASS: set_cmdline_or_bootconfig returned ret: {ret_val}")
            return True
        else:
            print(f"  FAIL: set_cmdline_or_bootconfig returned ret: {ret_val} (expected 0)")
            return False

    print("  PASS: set_cmdline_or_bootconfig command succeeded (rc=0)")
    return True


def test_cmdline_spoofed(target_cmdline, base_url=DEFAULT_SERVER_URL):
    """Verify /proc/cmdline returns the spoofed content from Termux shell."""
    print(f"\n=== Test: /proc/cmdline returns spoofed content ===")
    rc, out, err = adb_shell("cat /proc/cmdline", use_su=True, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: cat /proc/cmdline returned rc={rc}")
        print(f"  stderr: {err.strip() if err else '(none)'}")
        return False

    actual_cmdline = out.strip()
    print(f"  /proc/cmdline: '{actual_cmdline}'")
    print(f"  expected: '{target_cmdline}'")

    if actual_cmdline == target_cmdline:
        print("  PASS: /proc/cmdline matches spoofed content")
        return True
    else:
        print(f"  FAIL: /proc/cmdline is '{actual_cmdline}', expected '{target_cmdline}'")
        return False


def test_reset_cmdline_to_original(original_cmdline, test_file_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Restore original /proc/cmdline by writing original content to a file and
    calling set_cmdline_or_bootconfig with it."""
    print(f"\n=== Test: reset /proc/cmdline to original ===")

    # Write original cmdline to the test file
    cmd = f"printf '%s' '{original_cmdline}' > {test_file_path}"
    rc, out, err = adb_shell(cmd, use_su=use_su, base_url=base_url)
    if rc != 0:
        print(f"  FAIL: Failed to write original cmdline to test file (rc={rc})")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    # Set cmdline back to original
    rc, out, err = ksu_susfs(
        f"set_cmdline_or_bootconfig {test_file_path}",
        use_su=use_su,
        base_url=base_url,
    )

    print(f"  rc={rc}")
    print(f"  stdout: {out}")
    if err:
        print(f"  stderr: {err}")

    if rc != 0:
        print(f"  FAIL: set_cmdline_or_bootconfig (reset) returned rc={rc}")
        print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

    ret_match = re.search(r"ret:\s*(-?\d+)", out)
    if ret_match:
        ret_val = int(ret_match.group(1))
        if ret_val == 0:
            print(f"  PASS: reset returned ret: {ret_val}")
            return True
        else:
            print(f"  FAIL: reset returned ret: {ret_val} (expected 0)")
            return False

    print("  PASS: reset command succeeded (rc=0)")
    return True


def test_cmdline_restored(original_cmdline, base_url=DEFAULT_SERVER_URL):
    """Verify /proc/cmdline returns to original content after reset."""
    print(f"\n=== Test: /proc/cmdline restored to original ===")
    time.sleep(1)
    rc, out, err = adb_shell("cat /proc/cmdline", use_su=True, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: cat /proc/cmdline returned rc={rc}")
        print(f"  stderr: {err.strip() if err else '(none)'}")
        return False

    actual_cmdline = out.strip()
    print(f"  /proc/cmdline: '{actual_cmdline}'")
    print(f"  expected: '{original_cmdline}'")

    if actual_cmdline == original_cmdline:
        print("  PASS: /proc/cmdline restored to original content")
        return True
    else:
        print(f"  FAIL: /proc/cmdline is '{actual_cmdline}', expected '{original_cmdline}'")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Test SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG functionality via HTTP remote server"
    )
    parser.add_argument(
        "--target-cmdline",
        required=True,
        help="Spoofed cmdline string (e.g., console=tty0 susfs_test)",
    )
    parser.add_argument(
        "--test-file-path",
        required=True,
        help="Path on device to write the test file (e.g., /data/local/tmp/fake_cmdline)",
    )
    parser.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"Base URL of the remote server (default: {DEFAULT_SERVER_URL})",
    )

    args = parser.parse_args()

    target_cmdline = args.target_cmdline
    test_file_path = args.test_file_path
    base_url = args.server_url

    print("=" * 60)
    print("SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG Test Suite")
    print("=" * 60)
    print(f"Target cmdline: {target_cmdline}")
    print(f"Test file path: {test_file_path}")
    print(f"Server URL: {base_url}")
    print()

    if not check_server(base_url=base_url):
        sys.exit(1)

    # Capture original /proc/cmdline before spoofing for restore verification
    rc_orig, out_orig, _ = adb_shell("cat /proc/cmdline", use_su=True, base_url=base_url)
    original_cmdline = out_orig.strip() if rc_orig == 0 else "unknown"
    print(f"Original cmdline captured: '{original_cmdline}'")
    print()

    results = []

    # Test 1: Check enabled features
    results.append(("show enabled_features", test_enabled_features(use_su=True, base_url=base_url)))

    # Test 2: Create test file with spoofed content
    results.append(("create test file",
                    test_create_test_file(test_file_path, target_cmdline, use_su=True, base_url=base_url)))

    # Test 3: Set spoofed cmdline
    results.append(("set_cmdline_or_bootconfig",
                    test_set_cmdline_or_bootconfig(test_file_path, use_su=True, base_url=base_url)))

    # Small delay to ensure the change is applied
    time.sleep(1)

    # Test 4: Verify /proc/cmdline is spoofed
    results.append(("cmdline spoofed", test_cmdline_spoofed(target_cmdline, base_url=base_url)))

    # Test 5: Reset cmdline to original
    results.append(("reset cmdline to original",
                    test_reset_cmdline_to_original(original_cmdline, test_file_path, use_su=True, base_url=base_url)))

    # Small delay to ensure the reset is applied
    time.sleep(1)

    # Test 6: Verify /proc/cmdline restored
    results.append(("cmdline restored", test_cmdline_restored(original_cmdline, base_url=base_url)))

    # Cleanup: remove test file
    print(f"\n=== Cleanup: remove {test_file_path} ===")
    rc, out, err = adb_shell(f"rm -f {test_file_path}", use_su=True, base_url=base_url)
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
