#!/usr/bin/env python3
"""Legacy entry point — delegates to the modular app.

The original 300KB+ implementation lives in app/server.py.
This shim preserves `python server.py` for existing scripts.
"""
from app.server import run_server

if __name__ == "__main__":
    run_server()