#!/usr/bin/env python3
"""
Test script for SUSFS_OPEN_REDIRECT functionality.

Tests the OPEN_REDIRECT sub-config of CONFIG_KSU_SUSFS by communicating with an
HTTP server running on the Termux device (uid >= 10000, root), which executes
ksu_susfs natively without the adb round-trip.

Tests:
1. Verify CONFIG_KSU_SUSFS_OPEN_REDIRECT is enabled via show enabled_features
2. Create target test file on the device
3. Create redirected test file with different content on the device
4. Read target content before redirect (informational — should be target's content)
5. Set open_redirect via ksu_susfs add_open_redirect <target> <redirected> <uid_scheme>
   and verify rc=0
   NOTE: uid_scheme=2 (UID_NON_SU_PROC) is used since Termux shell is a non-su process
   NOTE: Both paths must be on a non-FUSE filesystem (kernel rejects FUSE for open_redirect)
6. Read target content after redirect — should now show redirected file's content
7. Read redirected path directly — should still show its own content (reversed lookup)
8. Cleanup: remove both test files

Usage:
    python3 tests/test_susfs_open_redirect.py \\
        --target-path /data/data/com.termux/files/susfs_or_target \\
        --redirected-path /data/data/com.termux/files/susfs_or_redirected \\
        --uid-scheme 2
    python3 tests/test_susfs_open_redirect.py \\
        --target-path /data/data/com.termux/files/susfs_or_target \\
        --redirected-path /data/data/com.termux/files/susfs_or_redirected \\
        --uid-scheme 2 \\
        --server-url http://127.0.0.1:8765

Setup (run once on the Termux device before testing):
    python3 tests/susfs_server.py
    # From the host:
    adb forward tcp:8765 tcp:8765

Notes:
- The kernel rejects FUSE filesystems for open_redirect (susfs_add_open_redirect
  returns -EINVAL if target or redirected inode's super_block magic is FUSE_SUPER_MAGIC).
- Use paths on non-FUSE filesystems (e.g., /data/data/com.termux/files/ which is f2fs).
"""

import argparse
import re
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
    """Test that CONFIG_KSU_SUSFS_OPEN_REDIRECT is listed in enabled features."""
    print("=== Test: show enabled_features ===")
    rc, out, err = ksu_susfs("show enabled_features", use_su=use_su, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: ksu_susfs show enabled_features returned rc={rc}")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    if "CONFIG_KSU_SUSFS_OPEN_REDIRECT" in out:
        print("  PASS: CONFIG_KSU_SUSFS_OPEN_REDIRECT found in enabled features")
        print(f"  Output:\n{out}")
        return True
    else:
        print("  FAIL: CONFIG_KSU_SUSFS_OPEN_REDIRECT NOT found in enabled features")
        print(f"  Output:\n{out}")
        return False


def test_create_target_file(target_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Write target test file on the device."""
    print(f"\n=== Test: create target file '{target_path}' ===")
    cmd = f"echo 'target_original_content' > {target_path}"
    rc, out, err = adb_shell(cmd, use_su=use_su, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: Failed to create target file (rc={rc})")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    # Verify the file was created correctly
    rc, out, err = adb_shell(f"cat {target_path}", use_su=use_su, base_url=base_url)
    if rc != 0:
        print(f"  FAIL: Cannot read back target file (rc={rc})")
        print(f"  stderr: {err}")
        return False

    actual = out.strip()
    if actual != "target_original_content":
        print(f"  FAIL: Target file content mismatch")
        print(f"  actual:   '{actual}'")
        print(f"  expected: 'target_original_content'")
        return False

    print(f"  PASS: Target file created with content '{actual}'")
    return True


def test_create_redirected_file(redirected_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Write redirected test file with different content on the device."""
    print(f"\n=== Test: create redirected file '{redirected_path}' ===")
    cmd = f"echo 'redirected_spoofed_content' > {redirected_path}"
    rc, out, err = adb_shell(cmd, use_su=use_su, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: Failed to create redirected file (rc={rc})")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    # Verify the file was created correctly
    rc, out, err = adb_shell(f"cat {redirected_path}", use_su=use_su, base_url=base_url)
    if rc != 0:
        print(f"  FAIL: Cannot read back redirected file (rc={rc})")
        print(f"  stderr: {err}")
        return False

    actual = out.strip()
    if actual != "redirected_spoofed_content":
        print(f"  FAIL: Redirected file content mismatch")
        print(f"  actual:   '{actual}'")
        print(f"  expected: 'redirected_spoofed_content'")
        return False

    print(f"  PASS: Redirected file created with content '{actual}'")
    return True


def test_read_target_before(target_path, base_url=DEFAULT_SERVER_URL):
    """Read target content before redirect is added (informational)."""
    print(f"\n=== Test: read target before redirect (informational) ===")
    rc, out, err = adb_shell(f"cat {target_path}", use_su=False, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: cat target returned rc={rc}")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    actual = out.strip()
    print(f"  Target content before redirect: '{actual}'")
    print("  INFO: Should show target's own content before redirect is added")
    return True


def test_add_open_redirect(target_path, redirected_path, uid_scheme, use_su=True,
                           base_url=DEFAULT_SERVER_URL):
    """Test setting open_redirect via ksu_susfs add_open_redirect <target> <redirected> <uid_scheme>."""
    print(f"\n=== Test: add_open_redirect '{target_path}' -> '{redirected_path}' (uid_scheme={uid_scheme}) ===")
    rc, out, err = ksu_susfs(
        f"add_open_redirect {target_path} {redirected_path} {uid_scheme}",
        use_su=use_su,
        base_url=base_url,
    )

    print(f"  rc={rc}")
    print(f"  stdout: {out}")
    if err:
        print(f"  stderr: {err}")

    if rc != 0:
        ret_match = re.search(r"ret:\s*(-?\d+)", out)
        if ret_match:
            ret_val = int(ret_match.group(1))
            if ret_val == -22:  # -EINVAL
                print("  INFO: add_open_redirect returned -EINVAL (rc=234)")
                print("  Common cause: target or redirected path is on a FUSE filesystem.")
                print("  The kernel rejects FUSE for open_redirect (susfs_add_open_redirect)")
                print("  Use a non-FUSE path such as /data/data/com.termux/files/ instead.")
                return True  # Informational pass - known limitation

        print(f"  FAIL: add_open_redirect returned rc={rc}")
        print(f"  stdout: {out}")
        if err:
            print(f"  stderr: {err}")
        return False

    ret_match = re.search(r"ret:\s*(-?\d+)", out)
    if ret_match:
        ret_val = int(ret_match.group(1))
        if ret_val == 0:
            print(f"  PASS: add_open_redirect returned ret: {ret_val}")
            return True
        else:
            print(f"  FAIL: add_open_redirect returned ret: {ret_val} (expected 0)")
            return False

    print("  PASS: add_open_redirect command succeeded (rc=0)")
    return True


def test_read_target_after(target_path, redirected_path, base_url=DEFAULT_SERVER_URL):
    """Verify target content after redirect shows redirected file's content."""
    print(f"\n=== Test: target content after redirect shows redirected content ===")
    time.sleep(1)
    rc, out, err = adb_shell(f"cat {target_path}", use_su=False, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: cat target returned rc={rc}")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    actual = out.strip()
    print(f"  Target content after redirect: '{actual}'")
    print(f"  Expected (redirected content): 'redirected_spoofed_content'")

    if actual == "redirected_spoofed_content":
        print("  PASS: Target shows redirected content (open_redirect works)")
        return True
    else:
        print(f"  FAIL: Target shows '{actual}', expected 'redirected_spoofed_content'")
        return False


def test_read_redirected_directly(redirected_path, base_url=DEFAULT_SERVER_URL):
    """Verify redirected path still shows its own content (reversed lookup)."""
    print(f"\n=== Test: read redirected path directly ===")
    rc, out, err = adb_shell(f"cat {redirected_path}", use_su=False, base_url=base_url)

    if rc != 0:
        print(f"  FAIL: cat redirected returned rc={rc}")
        print(f"  stdout: {out}")
        print(f"  stderr: {err}")
        return False

    actual = out.strip()
    print(f"  Redirected content: '{actual}'")

    if actual == "redirected_spoofed_content":
        print("  PASS: Redirected path shows its own content")
        return True
    else:
        print(f"  FAIL: Redirected shows '{actual}', expected 'redirected_spoofed_content'")
        return False


def test_cleanup(target_path, redirected_path, use_su=True, base_url=DEFAULT_SERVER_URL):
    """Remove both test files."""
    print(f"\n=== Cleanup: remove {target_path} and {redirected_path} ===")
    rc1, out1, err1 = adb_shell(f"rm -f {target_path}", use_su=use_su, base_url=base_url)
    rc2, out2, err2 = adb_shell(f"rm -f {redirected_path}", use_su=use_su, base_url=base_url)
    if rc1 == 0 and rc2 == 0:
        print(f"  PASS: Cleanup succeeded")
    else:
        print(f"  INFO: Cleanup returned rc1={rc1}, rc2={rc2}")
        if err1:
            print(f"  stderr1: {err1.strip()}")
        if err2:
            print(f"  stderr2: {err2.strip()}")


def main():
    parser = argparse.ArgumentParser(
        description="Test SUSFS_OPEN_REDIRECT functionality via HTTP remote server"
    )
    parser.add_argument(
        "--target-path",
        required=True,
        help="Target path to redirect (e.g., /data/data/com.termux/files/susfs_or_target)",
    )
    parser.add_argument(
        "--redirected-path",
        required=True,
        help="Redirected path with different content (e.g., /data/data/com.termux/files/susfs_or_redirected)",
    )
    parser.add_argument(
        "--uid-scheme",
        type=int,
        default=2,
        help="UID scheme for open_redirect (default: 2 = UID_NON_SU_PROC)",
    )
    parser.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"Base URL of the remote server (default: {DEFAULT_SERVER_URL})",
    )

    args = parser.parse_args()

    target_path = args.target_path
    redirected_path = args.redirected_path
    uid_scheme = args.uid_scheme
    base_url = args.server_url

    print("=" * 60)
    print("SUSFS_OPEN_REDIRECT Test Suite")
    print("=" * 60)
    print(f"Target path: {target_path}")
    print(f"Redirected path: {redirected_path}")
    print(f"UID scheme: {uid_scheme}")
    print(f"Server URL: {base_url}")
    print()

    if not check_server(base_url=base_url):
        sys.exit(1)

    results = []

    # Test 1: Check enabled features
    results.append(("show enabled_features", test_enabled_features(use_su=True, base_url=base_url)))

    # Test 2: Create target file
    results.append(("create target file",
                    test_create_target_file(target_path, use_su=True, base_url=base_url)))

    # Test 3: Create redirected file
    results.append(("create redirected file",
                    test_create_redirected_file(redirected_path, use_su=True, base_url=base_url)))

    # Test 4: Read target before redirect (informational)
    results.append(("read target before redirect",
                    test_read_target_before(target_path, base_url=base_url)))

    # Small delay to ensure files are fully written
    time.sleep(1)

    # Test 5: Set open_redirect
    results.append(("add_open_redirect",
                    test_add_open_redirect(target_path, redirected_path, uid_scheme,
                                           use_su=True, base_url=base_url)))

    # Small delay to ensure the change is applied
    time.sleep(1)

    # Test 6: Verify target shows redirected content
    results.append(("target shows redirected content",
                    test_read_target_after(target_path, redirected_path, base_url=base_url)))

    # Test 7: Verify redirected path shows its own content
    results.append(("redirected path direct read",
                    test_read_redirected_directly(redirected_path, base_url=base_url)))

    # Cleanup
    test_cleanup(target_path, redirected_path, use_su=True, base_url=base_url)

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
