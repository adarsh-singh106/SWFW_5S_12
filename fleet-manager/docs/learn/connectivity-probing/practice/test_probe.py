"""
Automated Test Suite for Practice 05: SSH Banner Probe Engine
Verifies:
  Case 1: Live OpenSSH Server (RFC 4253 Banner Success)
  Case 2: Non-SSH Service (Port open, but returns HTTP/other protocol)
  Case 3: Unreachable / Silent Drop (Timeout test)
"""

import socket
import threading
import sys

# Ensure UTF-8 output if supported
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from probe_engine import probe_ssh_endpoint


def run_all_probe_tests():
    print("=" * 65)
    print("RUNNING PRACTICE 05: PROBE ENGINE VERIFICATION")
    print("=" * 65)

    # -------------------------------------------------------------
    # CASE 1: Live OpenSSH Server Handshake
    # -------------------------------------------------------------
    print("\n[TEST 1] Testing Valid OpenSSH Server (Mock on port 2224)...")
    server1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server1.bind(("127.0.0.1", 2224))
    server1.listen(1)

    def handle_ssh_client():
        try:
            conn, _ = server1.accept()
            # Send RFC 4253 compliant OpenSSH banner
            conn.sendall(b"SSH-2.0-OpenSSH_9.0p1 Ubuntu-1ubuntu1\r\n")
            conn.close()
        except OSError:
            pass

    t1 = threading.Thread(target=handle_ssh_client)
    t1.start()

    res1 = probe_ssh_endpoint("127.0.0.1", 2224, timeout=2.0)
    server1.close()
    t1.join()

    print(f"  -> Result: {res1}")
    assert res1["reachable"] is True, "Test 1 Failed: Expected reachable True"
    assert "OpenSSH_9.0" in res1["banner"], "Test 1 Failed: Expected banner text"
    print("  -> [PASS] Valid SSH Banner correctly detected with latency!")

    # -------------------------------------------------------------
    # CASE 2: Non-SSH Service (e.g., Apache / Nginx HTTP Server)
    # -------------------------------------------------------------
    print("\n[TEST 2] Testing Non-SSH Service (Mock HTTP Server on port 2225)...")
    server2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server2.bind(("127.0.0.1", 2225))
    server2.listen(1)

    def handle_http_client():
        try:
            conn, _ = server2.accept()
            # Send HTTP response instead of SSH
            conn.sendall(b"HTTP/1.1 200 OK\r\nServer: Apache\r\n\r\n")
            conn.close()
        except OSError:
            pass

    t2 = threading.Thread(target=handle_http_client)
    t2.start()

    res2 = probe_ssh_endpoint("127.0.0.1", 2225, timeout=2.0)
    server2.close()
    t2.join()

    print(f"  -> Result: {res2}")
    assert res2["reachable"] is False, "Test 2 Failed: Expected reachable False"
    assert "not SSH" in res2["error"], "Test 2 Failed: Expected 'not SSH' error"
    print("  -> [PASS] Non-SSH service gracefully caught without crashing!")

    # -------------------------------------------------------------
    # CASE 3: Unreachable / Silent Drop (RFC 5737 Blackhole IP)
    # -------------------------------------------------------------
    print("\n[TEST 3] Testing Packet Drop / Timeout (RFC 5737 192.0.2.1)...")
    res3 = probe_ssh_endpoint("192.0.2.1", 22, timeout=1.0)
    print(f"  -> Result: {res3}")
    assert res3["reachable"] is False, "Test 3 Failed: Expected reachable False"
    assert "timed out" in res3["error"], "Test 3 Failed: Expected timeout error"
    print("  -> [PASS] Bounded timeout expired cleanly without hanging!")

    print("\n" + "=" * 65)
    print("ALL 3 PROBE TESTS PASSED SUCCESSFULLY! (EXIT CODE 0)")
    print("=" * 65)


if __name__ == "__main__":
    run_all_probe_tests()
