import socket
import time


def probe_ssh_endpoint(address: str, port: int, timeout: float = 2.5) -> dict:
    """
    Probes an SSH endpoint by completing a TCP handshake and verifying
    the RFC 4253 SSH identification banner without authenticating.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Bounded execution: Never leave timeout as None to avoid indefinite hangs
    s.settimeout(timeout)

    try:
        start_time = time.perf_counter()
        s.connect((address, port))
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # OpenSSH servers send their identification banner immediately upon TCP connect
        raw_bytes = s.recv(256)
        banner = raw_bytes.decode("utf-8", errors="replace").strip()

        if not banner.startswith("SSH-"):
            raise ValueError(f"Port is open, but service is not SSH (received: {banner[:30]!r})")

        return {
            "reachable": True,
            "banner": banner,
            "latency_ms": latency_ms,
            "error": None
        }

    except ValueError as e:
        return {
            "reachable": False,
            "banner": None,
            "latency_ms": None,
            "error": str(e)
        }
    except ConnectionRefusedError:
        return {
            "reachable": False,
            "banner": None,
            "latency_ms": None,
            "error": "Connection refused (Host is alive, but SSH service is not running on this port)"
        }
    except (socket.timeout, TimeoutError):
        return {
            "reachable": False,
            "banner": None,
            "latency_ms": None,
            "error": "Connection timed out (Host powered off, network partitioned, or firewall dropped packets)"
        }
    except OSError as e:
        return {
            "reachable": False,
            "banner": None,
            "latency_ms": None,
            "error": f"OS network error: {e}"
        }
    finally:
        s.close()
