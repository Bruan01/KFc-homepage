from django.urls import path
from . import views
urlpatterns=[
 path("api/admin/publish-requests",views.publish_requests),
 path("api/admin/publish-requests/<int:request_id>/vote",views.vote),
 path("api/admin/inbox",views.inbox),
 path("api/admin/delete-requests/<int:request_id>/approve",lambda r,request_id:views.review_delete(r,request_id,"approve")),
 path("api/admin/delete-requests/<int:request_id>/reject",lambda r,request_id:views.review_delete(r,request_id,"reject")),
]
