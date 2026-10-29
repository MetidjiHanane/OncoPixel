"""Entry point used by the desktop shell and for local runs.

    python -m oncopixel.server [--port 8765] [--data-dir DIR]

Prints ``ONCOPIXEL_READY <port>`` on stdout once the socket is open so the Electron main
process knows when to load the interface. Binds to 127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys

# MPS operators without a native kernel fall back to the CPU instead of failing.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="OncoPixel local backend")
    ap.add_argument("--port", type=int, default=0, help="0 picks a free port")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--frontend-dir", default=None)
    args = ap.parse_args(argv)

    import uvicorn

    from .main import create_app

    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", args.port))
    port = sock.getsockname()[1]
    app = create_app(args.data_dir, args.frontend_dir)
    config = uvicorn.Config(app, log_level="warning")
    server = uvicorn.Server(config)
    print(f"ONCOPIXEL_READY {port}", flush=True)
    server.run(sockets=[sock])


if __name__ == "__main__":
    main(sys.argv[1:])
