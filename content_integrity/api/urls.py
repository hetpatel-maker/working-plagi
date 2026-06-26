from django.urls import path

from . import views

app_name = "content_integrity"

urlpatterns = [
    path("v1/courses/<str:course_id>/report/", views.CourseReportView.as_view(), name="course-report"),
    path("v1/courses/<str:course_id>/report/download/", views.CourseReportDownloadView.as_view(), name="course-report-download"),
    path("v1/courses/<str:course_id>/blocks/", views.CourseBlockChecksView.as_view(), name="course-blocks"),
    path("v1/copyleaks-webhook/<str:scan_id>/<str:status>/", views.CopyleaksWebhookView.as_view(), name="copyleaks-webhook"),
    path("v1/copyleaks-pdf-webhook/<str:scan_id>/", views.CopyleaksPdfWebhookView.as_view(), name="copyleaks-pdf-webhook"),
]
