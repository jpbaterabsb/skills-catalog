"""Fixtures for end-to-end tests: a real catalog API process on a free port."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BIN = Path(sys.executable).parent


@pytest.fixture
def anyio_backend():
    return "asyncio"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def catalog_url(tmp_path):
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [str(BIN / "skills-catalog-api"), "--port", str(port), "--data", str(tmp_path / "data")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if proc.poll() is not None or time.monotonic() > deadline:
                pytest.fail("catalog API did not start")
            time.sleep(0.1)
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)
