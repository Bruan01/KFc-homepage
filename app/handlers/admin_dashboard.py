"""Compatibility wrapper for the admin dashboard handler."""


def handle_admin_dashboard_get(handler):
    return handler.dashboard_get()
