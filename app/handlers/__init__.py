"""
Handler package — domain-specific HTTP handlers.
Each module exports a `register(handler_class)` function or is auto-discovered.

Import order matters: base.py first, then domain modules.
"""
# Import base first so AppHandler class exists
# Then domain modules will be imported elsewhere (e.g., in server.py)
