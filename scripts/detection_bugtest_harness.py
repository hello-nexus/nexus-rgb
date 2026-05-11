#!/usr/bin/env python3
"""
OpenRGB headless cold-start reliability test harness.

Runs an isolated OpenRGB-headless.exe N times on a custom port with a custom
config dir, waits for detection to stabilize, queries device count + names
over the SDK, kills the process, and logs per-run results.

Does not touch the production OpenRGB instance on port 6742.
"""
import argparse
import json
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

HEADER_SIZE = 16
MAGIC = b"ORGB"
PKT_REQUEST_CONTROLLER_COUNT = 0
PKT_REQUEST_CONTROLLER_DATA  = 1
PKT_SET_CLIENT_NAME          = 50


def pack_header(dev_idx, pkt_id, pkt_size):
    return MAGIC + struct.pack("<III", dev_idx, pkt_id, pkt_size)


def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("socket closed")
        buf += chunk
    return buf


def send_set_client_name(sock, name="bugtest"):
    payload = name.encode("utf-8") + b"\x00"
    sock.sendall(pack_header(0, PKT_SET_CLIENT_NAME, len(payload)) + payload)


def recv_packet(sock, expected_pkt_id):
    hdr = recv_exact(sock, HEADER_SIZE)
    if hdr[:4] != MAGIC:
        raise RuntimeError(f"bad magic {hdr[:4]!r}")
    dev_idx, pkt_id, pkt_size = struct.unpack("<III", hdr[4:])
    if pkt_id != expected_pkt_id:
        raise RuntimeError(f"got pkt_id {pkt_id}, wanted {expected_pkt_id}")
    return dev_idx, (recv_exact(sock, pkt_size) if pkt_size else b"")


def get_count(sock):
    sock.sendall(pack_header(0, PKT_REQUEST_CONTROLLER_COUNT, 0))
    _, data = recv_packet(sock, PKT_REQUEST_CONTROLLER_COUNT)
    return struct.unpack("<I", data)[0]


def get_name(sock, idx):
    sock.sendall(pack_header(idx, PKT_REQUEST_CONTROLLER_DATA, 0))
    _, data = recv_packet(sock, PKT_REQUEST_CONTROLLER_DATA)
    if len(data) < 10:
        return "(short)"
    # layout: uint32 total_size, int32 device_type, uint16 name_len, char[name_len] name
    off = 8
    name_len = struct.unpack_from("<H", data, off)[0]
    off += 2
    raw = data[off:off + name_len]
    return raw.rstrip(b"\x00").decode("utf-8", errors="replace")


def wait_port(host, port, timeout):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def wait_stable(host, port, stable_polls=12, interval=1.0, max_wait=60.0):
    end = time.time() + max_wait
    last = -1
    streak = 0
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=3) as s:
                send_set_client_name(s)
                count = get_count(s)
            if count == last:
                streak += 1
                if streak >= stable_polls:
                    return count
            else:
                last = count
                streak = 0
        except Exception:
            streak = 0
        time.sleep(interval)
    return last


def final_list(host, port):
    try:
        with socket.create_connection((host, port), timeout=5) as s:
            send_set_client_name(s)
            count = get_count(s)
            names = []
            for i in range(count):
                try:
                    names.append(get_name(s, i))
                except Exception as e:
                    names.append(f"(err:{e})")
            return count, names
    except Exception as e:
        return -1, [f"(query failed: {e})"]


def run_once(exe, port, config, run_idx, log_dir, verbose=False):
    log_file = log_dir / f"run_{run_idx:03d}.txt"
    start = time.time()
    cmd = [
        str(exe),
        "--server",
        "--server-port", str(port),
        "--server-host", "127.0.0.1",
        "--noautoconnect",
        "--config", str(config),
    ]
    if verbose:
        cmd.append("-vv")
    with open(log_file, "w") as lf:
        proc = subprocess.Popen(
            cmd,
            stdout=lf,
            stderr=subprocess.STDOUT,
        )
    result = {"run": run_idx, "pid": proc.pid}
    try:
        if not wait_port(host="127.0.0.1", port=port, timeout=15):
            result["error"] = "port never opened"
            return result
        result["port_open_ms"] = int((time.time() - start) * 1000)
        stable_count = wait_stable("127.0.0.1", port)
        result["stable_ms"] = int((time.time() - start) * 1000)
        count, names = final_list("127.0.0.1", port)
        result["count"] = count
        result["names"] = names
    finally:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception:
            pass
        result["exit_code"] = proc.returncode
        result["total_ms"] = int((time.time() - start) * 1000)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--port", type=int, default=16742)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--log-dir", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--cooldown", type=float, default=2.0)
    ap.add_argument("--verbose", action="store_true", help="Pass -vv to OpenRGB")
    args = ap.parse_args()

    exe = Path(args.exe)
    config = Path(args.config)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    # Wipe config to force true cold start each batch
    # (but preserve across runs within a batch so OpenRGB picks up any prior state;
    # actually the user wants cold-start bug repro, so wipe once at start is fine)

    results = []
    print(f"{'run':>4} {'count':>6} {'stable_ms':>10} {'total_ms':>9} {'exit':>5}")
    print("-" * 44)
    for i in range(1, args.runs + 1):
        r = run_once(exe, args.port, config, i, log_dir, verbose=args.verbose)
        results.append(r)
        count = r.get("count", "ERR")
        err = r.get("error", "")
        print(f"{i:>4} {str(count):>6} {str(r.get('stable_ms', '-')):>10} {str(r.get('total_ms', '-')):>9} {str(r.get('exit_code', '-')):>5}  {err}")
        sys.stdout.flush()
        time.sleep(args.cooldown)

    counts = [r["count"] for r in results if r.get("count", -1) >= 0]
    print()
    print("=== Summary ===")
    print(f"total runs: {len(results)}")
    print(f"successful queries: {len(counts)}")
    if counts:
        print(f"min/max/mean: {min(counts)}/{max(counts)}/{sum(counts)/len(counts):.2f}")
        for c in sorted(set(counts)):
            print(f"  count={c}: {counts.count(c)} runs")

    Path(args.output).write_text(json.dumps(results, indent=2))
    print(f"\nFull results -> {args.output}")


if __name__ == "__main__":
    main()
