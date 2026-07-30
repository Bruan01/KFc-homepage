"""Application route declarations.

This module is the single URL-to-handler map.  Domain handlers stay in
``app.handlers``; routing no longer imports them through string reflection.
"""
from http import HTTPStatus

from app.handlers import (
    admin_agnes_keys,
    admin_products,
    admin_requests,
    admin_settings,
    agnes_chat,
    agnes_video,
    auth_admin,
    auth_user,
    chunk_uploads,
    download,
    points,
    product,
    publish,
    subscribe,
    user,
)
from app.utils.helpers import now_iso
from app.utils.routes import dispatch, register, route


@route("GET", r"/api/health")
def health(handler):
    handler.send_json({"ok": True, "time": now_iso()})


@route("GET", r"/api/admin/dashboard")
def admin_dashboard(handler):
    handler.dashboard_get()


@route("GET", r"/material/.+", path_mode="path")
def material_file(handler, path):
    handler.serve_material_file(path)


@route("POST", r"/api/admin/register")
def legacy_admin_register(handler):
    handler.send_json(
        {"error": "legacy admin registration disabled; use unified registration at /api/user/register"},
        status=HTTPStatus.GONE,
    )


# GET — account, points and admin metadata.
register("GET", r"/api/user/me", auth_user.handle_user_me)
register("GET", r"/api/account/me", auth_user.handle_account_me)
register("GET", r"/api/user/history", user.handle_user_history)
register("GET", r"/api/user/download-quota", user.handle_user_download_quota)
register("GET", r"/api/user/requests", user.handle_user_requests)
register("GET", r"/api/user/notifications", user.handle_user_notifications)
register("GET", r"/api/points/me", points.handle_points_me)
register("GET", r"/api/points/rules", points.handle_points_rules)
register("GET", r"/api/points/ledger", points.handle_points_ledger, path_mode="raw_path")
register("GET", r"/api/points/download-entitlements", points.handle_points_entitlements)
register(
    "GET",
    r"/api/admin/download-requests",
    admin_requests.handle_admin_download_requests_get,
    path_mode="raw_path",
)
register("GET", r"/api/admin/users", auth_admin.handle_admin_users_get)
register("GET", r"/api/admin/me", auth_admin.handle_admin_me)
register("GET", r"/api/admin/tokens", auth_admin.handle_admin_tokens_get)
register("GET", r"/api/admin/agnes-keys", admin_agnes_keys.handle_admin_agnes_keys_get)
register("GET", r"/api/admin/upload-settings", admin_settings.handle_admin_upload_settings_get)
register("GET", r"/api/admin/points/settings", points.handle_admin_points_settings_get)
register("GET", r"/api/admin/points/accounts", points.handle_admin_points_accounts, path_mode="raw_path")
register("GET", r"/api/admin/chat-model-config", agnes_chat.handle_admin_chat_model_config_get)
register("GET", r"/api/admin/publish-requests", publish.handle_publish_requests_get)
register("GET", r"/api/admin/inbox", publish.handle_admin_inbox_get)

# GET — products, packages, Agnes and downloads.  Specific product routes are
# registered before the generic product-detail route.
register("GET", r"/api/products", product.handle_public_products)
register("GET", r"/api/products/meta", product.handle_public_products_meta)
register("GET", r"/api/products/[^/]+", product.handle_public_product_detail, path_mode="path")
register("GET", r"/api/admin/versions/[^/]+", admin_products.handle_admin_versions_get, path_mode="path")
register(
    "GET",
    r"/api/admin/products/[^/]+/packages",
    admin_products.handle_admin_packages_get,
    path_mode="path",
)
register(
    "GET",
    r"/api/admin/products(?:/[^/]+)?",
    admin_products.handle_admin_products_get,
    path_mode="raw_path",
)
register("GET", r"/api/agnes/tasks", agnes_video.handle_agnes_tasks_get)
register("GET", r"/api/agnes/quota", agnes_video.handle_agnes_quota_get)
register("GET", r"/api/agnes/runtime", agnes_video.handle_agnes_runtime_get)
register("GET", r"/api/agnes/chat-sessions", agnes_chat.handle_agnes_chat_sessions_get)
register("GET", r"/api/agnes/chat-config", agnes_chat.handle_agnes_chat_config_get)
register("GET", r"/api/agnes/public-videos", agnes_video.handle_agnes_public_videos_get)
register("GET", r"/api/agnes/videos/[^/]+", agnes_video.handle_agnes_video_get, path_mode="path")
register(
    "GET",
    r"/api/admin/agnes-video-requests",
    admin_requests.handle_admin_agnes_video_requests_get,
    path_mode="raw_path",
)
# The raw path is intentional: package selection lives in ``?pkg=<id>``.
register("GET", r"/download/[^/]+", download.handle_download, path_mode="raw_path")

# POST — authentication and settings.
register("POST", r"/api/admin/login", auth_admin.handle_admin_login)
register("POST", r"/api/admin/logout", auth_admin.handle_admin_logout)
register("POST", r"/api/admin/tokens", auth_admin.handle_admin_tokens_create)
register("POST", r"/api/admin/agnes-keys", admin_agnes_keys.handle_admin_agnes_keys_create)
register("POST", r"/api/admin/upload-settings", admin_settings.handle_admin_upload_settings_update)
register("POST", r"/api/admin/points/settings", points.handle_admin_points_settings_update)
register("POST", r"/api/admin/points/adjust", points.handle_admin_points_adjust)
register("POST", r"/api/admin/points/freeze", points.handle_admin_points_freeze)
register("POST", r"/api/admin/points/unfreeze", points.handle_admin_points_unfreeze)
register("POST", r"/api/admin/chat-model-config", agnes_chat.handle_admin_chat_model_config_update)
register("POST", r"/api/admin/publish-requests", publish.handle_publish_request_create)
register(
    "POST",
    r"/api/admin/publish-requests/[^/]+/vote",
    publish.handle_publish_request_vote,
    path_mode="path",
)
register(
    "POST",
    r"/api/admin/delete-requests/[^/]+/approve",
    publish.handle_delete_request_approve,
    path_mode="path",
)
register(
    "POST",
    r"/api/admin/delete-requests/[^/]+/reject",
    publish.handle_delete_request_reject,
    path_mode="path",
)
register(
    "POST",
    r"/api/admin/versions/[^/]+/rollback",
    admin_products.handle_admin_version_rollback,
    path_mode="path",
)
register("POST", r"/api/user/verification-code", auth_user.handle_user_verification_code)
register("POST", r"/api/user/register", auth_user.handle_user_register)
register("POST", r"/api/user/login", auth_user.handle_user_login)
register("POST", r"/api/user/email/bind", auth_user.handle_user_email_bind)
register("POST", r"/api/user/logout", auth_user.handle_user_logout)
register("POST", r"/api/points/redeem-download", points.handle_points_redeem_download)
register("POST", r"/api/subscribe", subscribe.handle_subscribe)
register(
    "POST",
    r"/api/products/[^/]+/request-download",
    product.handle_user_download_request,
    path_mode="path",
)
register("POST", r"/api/admin/products", admin_products.handle_admin_products_create)
register(
    "POST",
    r"/api/admin/products/[^/]+/upload",
    admin_products.handle_admin_upload,
    path_mode="path",
)
register(
    "POST",
    r"/api/admin/download-requests/[^/]+/approve",
    admin_requests.handle_admin_download_request_approve,
    path_mode="path",
)
register(
    "POST",
    r"/api/admin/download-requests/[^/]+/reject",
    admin_requests.handle_admin_download_request_reject,
    path_mode="path",
)
register(
    "POST",
    r"/api/admin/products/[^/]+/upload-sessions",
    chunk_uploads.handle_admin_chunk_upload_create,
    path_mode="path",
)
register(
    "POST",
    r"/api/admin/upload-sessions/[^/]+/complete",
    chunk_uploads.handle_admin_chunk_upload_complete,
    path_mode="path",
)
register(
    "POST",
    r"/api/admin/upload-sessions/[^/]+/chunks/[^/]+",
    chunk_uploads.handle_admin_chunk_upload_chunk,
    path_mode="path",
)
register("POST", r"/api/agnes/videos", agnes_video.handle_agnes_video_create)
register("POST", r"/api/agnes/requests", agnes_video.handle_agnes_video_request_create)
register("POST", r"/api/agnes/chat-sessions", agnes_chat.handle_agnes_chat_sessions_create)
register("POST", r"/api/agnes/chat", agnes_chat.handle_agnes_chat_create)
register(
    "POST",
    r"/api/admin/agnes-video-requests/[^/]+/approve",
    admin_requests.handle_admin_agnes_video_request_approve,
    path_mode="path",
)
register(
    "POST",
    r"/api/admin/agnes-video-requests/[^/]+/reject",
    admin_requests.handle_admin_agnes_video_request_reject,
    path_mode="path",
)

# PUT.
register("PUT", r"/api/agnes/tasks/[^/]+/public", agnes_video.handle_agnes_task_public_update, path_mode="path")
register("PUT", r"/api/admin/products/[^/]+", admin_products.handle_admin_products_update, path_mode="path")
register("PUT", r"/api/admin/agnes-keys/[^/]+", admin_agnes_keys.handle_admin_agnes_keys_update, path_mode="path")

# DELETE.
register(
    "DELETE",
    r"/api/agnes/chat-sessions/[^/]+",
    agnes_chat.handle_agnes_chat_session_delete,
    path_mode="path",
)
register("DELETE", r"/api/agnes/tasks/[^/]+", agnes_video.handle_agnes_task_delete, path_mode="path")
register("DELETE", r"/api/admin/packages/[^/]+", admin_products.handle_admin_packages_delete, path_mode="path")
register("DELETE", r"/api/admin/products/[^/]+", admin_products.handle_admin_products_delete, path_mode="path")
register("DELETE", r"/api/admin/agnes-keys/[^/]+", admin_agnes_keys.handle_admin_agnes_keys_delete, path_mode="path")

__all__ = ["dispatch"]
