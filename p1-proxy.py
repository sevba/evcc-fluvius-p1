#!/usr/bin/env python3
"""
Reads DSMR P1 telegrams from ser2net continuously, parses them,
and serves the latest snapshot as JSON on http://127.0.0.1:7071/
"""
import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"
SER2NET_PORT = 3333
HTTP_PORT = 7071

OBIS = {
    "pw_in":  r"1-0:1\.7\.0\(([0-9.]+)\*",
    "pw_ex":  r"1-0:2\.7\.0\(([0-9.]+)\*",
    "e_t1":   r"1-0:1\.8\.1\(([0-9.]+)\*",
    "e_t2":   r"1-0:1\.8\.2\(([0-9.]+)\*",
    "e_ex1":  r"1-0:2\.8\.1\(([0-9.]+)\*",
    "e_ex2":  r"1-0:2\.8\.2\(([0-9.]+)\*",
    "i1":     r"1-0:31\.7\.0\(([0-9.]+)\*",
    "i2":     r"1-0:51\.7\.0\(([0-9.]+)\*",
    "i3":     r"1-0:71\.7\.0\(([0-9.]+)\*",
}

state = {}
state_lock = threading.Lock()


def parse_telegram(lines):
    text = "\n".join(lines)
    raw = {}
    for key, pattern in OBIS.items():
        m = re.search(pattern, text, re.MULTILINE)
        raw[key] = float(m.group(1)) if m else 0.0
    return {
        "power":      round((raw["pw_in"] - raw["pw_ex"]) * 1000),
        "energy":     round(raw["e_t1"] + raw["e_t2"], 3),
        "energy_exp": round(raw["e_ex1"] + raw["e_ex2"], 3),
        "i1":         round(raw["i1"], 3),
        "i2":         round(raw["i2"], 3),
        "i3":         round(raw["i3"], 3),
    }


def reader():
    while True:
        try:
            sock = socket.create_connection((HOST, SER2NET_PORT), timeout=10)
            f = sock.makefile("rb")
            telegram = []
            in_telegram = False
            for raw_line in f:
                line = raw_line.decode("latin-1").rstrip("\r\n")
                if line.startswith("/"):
                    in_telegram = True
                    telegram = [line]
                elif in_telegram:
                    telegram.append(line)
                    if line.startswith("!"):
                        parsed = parse_telegram(telegram)
                        with state_lock:
                            state.update(parsed)
                        in_telegram = False
                        telegram = []
        except Exception:
            time.sleep(2)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with state_lock:
            body = json.dumps(state).encode()
        self.send_response(200 if state else 503)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


threading.Thread(target=reader, daemon=True).start()
print(f"P1 proxy listening on {HTTP_PORT}", flush=True)
HTTPServer((HOST, HTTP_PORT), Handler).serve_forever()
