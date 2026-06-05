#!/usr/bin/env python3
"""
KFlow Homepage — modular application entry point.
Run with: python -m app
"""
import os
import sys

# Ensure project root is on sys.path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from app.server import run_server

if __name__ == "__main__":
    run_server()
