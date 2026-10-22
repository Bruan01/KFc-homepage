from django.urls import path

from . import admin_community, onboarding, social, views

urlpatterns = [
    path("api/community/official", social.official_identity),
    path("api/admin/community/official", admin_community.official_community),
    path("api/users/mentions", social.connections, {"username": "", "kind": "mentions"}),
    path("api/users/<str:username>/social", social.social),
    path("api/users/<str:username>/follow", social.follow),
    path("api/users/<str:username>/following", social.connections, {"kind": "following"}),
    path("api/users/<str:username>/followers", social.connections, {"kind": "followers"}),
    path("api/user/verification-code", views.verification_code),
    path("api/user/register", views.register),
    path("api/user/activate-admin", views.activate_admin),
    path("api/user/guide-onboarding", onboarding.guide_onboarding),
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
