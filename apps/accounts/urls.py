from django.urls import path

from . import views

urlpatterns = [
    path("api/user/verification-code", views.verification_code),
    path("api/user/register", views.register),
    path("api/user/login", views.user_login),
    path("api/user/email/bind", views.email_bind),
    path("api/user/logout", views.user_logout),
    path("api/user/me", views.user_me),
    path("api/account/me", views.account_me),
    path("api/admin/login", views.admin_login),
    path("api/admin/logout", views.admin_logout),
    path("api/admin/me", views.admin_me),
    path("api/admin/register", views.legacy_admin_register),
    path("api/admin/tokens", views.tokens, name="admin-tokens"),
    path("api/admin/users", views.users_get),
]
