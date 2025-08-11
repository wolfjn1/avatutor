#!/usr/bin/env python3
from __future__ import annotations

import socket
import sys
import time
from typing import List


def wait(host: str, port: int) -> None:
    while True:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return
        except OSError:
            print(f"Waiting for {host}:{port}...")
            time.sleep(1)


def main(argv: List[str]) -> int:
    if len(argv) < 3:
        print("usage: wait_for_it.py HOST PORT -- CMD...")
        return 2
    host = argv[0]
    port = int(argv[1])
    rest = argv[2:]
    if rest[0] == "--":
        rest = rest[1:]
    wait(host, port)
    if rest:
        import subprocess

        return subprocess.call(rest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


