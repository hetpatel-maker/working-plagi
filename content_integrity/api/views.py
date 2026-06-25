import csv
import json
import logging
from django.http import StreamingHttpResponse, JsonResponse
from rest_framework.generics import RetrieveAPIView, ListAPIView
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from ..models import ContentCheck, CourseReport, ContentCheckStatus
from .permissions import IsCourseAuthor
from .serializers import ContentCheckSerializer, CourseReportSerializer

log = logging.getLogger(__name__)


class CourseReportView(RetrieveAPIView):
    """GET /api/content-integrity/v1/courses/<course_id>/report/"""
    permission_classes = [IsAuthenticated, IsCourseAuthor]
    serializer_class = CourseReportSerializer
    lookup_field = "course_id"
    lookup_url_kwarg = "course_id"
    queryset = CourseReport.objects.all()


class CourseBlockChecksView(ListAPIView):
    """GET /api/content-integrity/v1/courses/<course_id>/blocks/ - full per-block breakdown"""
    permission_classes = [IsAuthenticated, IsCourseAuthor]
    serializer_class = ContentCheckSerializer

    def get_queryset(self):
        return ContentCheck.objects.filter(course_id=self.kwargs["course_id"]).order_by("-score")


class CourseReportDownloadView(APIView):
    """GET /api/content-integrity/v1/courses/<course_id>/report/download/ - Download CSV report"""
    permission_classes = [IsAuthenticated, IsCourseAuthor]

    def get(self, request, course_id):
        checks = ContentCheck.objects.filter(course_id=course_id).order_by("-score", "usage_key")

        class Echo:
            def write(self, value):
                return value

        def generate():
            # Add UTF-8 BOM so Excel opens it perfectly aligned and formatted
            yield '\ufeff'
            
            writer = csv.writer(Echo())
                
            yield writer.writerow([
                "Usage Key", "Block Type", "Status", "Plagiarism Score", 
                "AI Generated %", "Grammar Score", "Readability", "Flag Reasons", 
                "Match Details", "Error Message", "Last Checked At"
            ])
            for check in checks:
                details = []
                for s in check.matched_sources:
                    if isinstance(s, dict):
                        url = str(s.get("url", "")).replace('\n', ' ').replace('\r', '')
                        title = str(s.get("title", "")).replace('\n', ' ').replace('\r', '')
                        words = s.get("matched_words", 0)
                        snippet = str(s.get("matched_snippet", "")).replace('\n', ' ').replace('\r', '')
                        text = f"Title: {title} | URL: {url} | Words: {words} | Snippet: {snippet}"
                        details.append(text)
                details_str = " || ".join(details)
                
                reasons = ", ".join(check.flag_reasons) if isinstance(check.flag_reasons, list) else ""
                clean_error = str(check.error_message).replace('\n', ' ').replace('\r', '')
                
                yield writer.writerow([
                    check.usage_key,
                    check.block_type,
                    check.status,
                    check.score if check.score is not None else "",
                    check.ai_score if check.ai_score is not None else "",
                    check.grammar_score if check.grammar_score is not None else "",
                    str(check.readability_text).replace('\n', ' ').replace('\r', ''),
                    str(reasons).replace('\n', ' ').replace('\r', ''),
                    details_str,
                    clean_error,
                    check.last_checked_at.isoformat() if check.last_checked_at else "",
                ])

        response = StreamingHttpResponse(generate(), content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = f'attachment; filename="content_integrity_report_{course_id}.csv"'
        return response


class CopyleaksWebhookView(APIView):
    """POST /api/content-integrity/v1/copyleaks-webhook/<scan_id>/<status>/"""
    # Copyleaks calls this, so we cannot use session authentication
    authentication_classes = []
    permission_classes = []

    def post(self, request, scan_id, status):
        log.info("[content_integrity] Webhook received for scan_id: %s with status: %s", scan_id, status)
        from django.conf import settings
        from django.utils import timezone
        
        # 1. Security Check
        secret = getattr(settings, "CONTENT_INTEGRITY_WEBHOOK_SECRET", "ci-secret-token")
        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {secret}":
            log.warning("[content_integrity] Unauthorized webhook attempt for %s", scan_id)
            return JsonResponse({"error": "Unauthorized"}, status=403)
        
        try:
            check = ContentCheck.objects.get(scan_id=scan_id)
        except ContentCheck.DoesNotExist:
            log.warning("[content_integrity] Webhook received for unknown scan_id: %s", scan_id)
            return JsonResponse({"error": "Unknown scan_id"}, status=404)

        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        # 2. Handle explicit error status from Copyleaks
        if status == "error":
            error_msg = payload.get("error", {}).get("message", "Unknown Copyleaks Error")
            log.error("[content_integrity] Scan %s errored on Copyleaks side: %s", scan_id, error_msg)
            check.status = ContentCheckStatus.ERROR
            check.error_message = error_msg
            check.save(update_fields=["status", "error_message", "updated_at"])
            
            from ..tasks import refresh_course_report
            refresh_course_report.delay(check.course_id)
            return JsonResponse({"status": "error recorded"})

        # Parse the webhook payload using the Copyleaks provider logic
        from ..providers.copyleaks import CopyleaksProvider
        provider = CopyleaksProvider()
        
        try:
            # We use the provider's _parse_result, which expects the same structure webhook.site returned
            result = provider._parse_result(payload)
        except Exception as e:
            log.error("[content_integrity] Failed to parse webhook payload for scan %s: %s", scan_id, e)
            check.status = ContentCheckStatus.ERROR
            check.error_message = f"Webhook parsing error: {e}"
            check.save(update_fields=["status", "error_message", "updated_at"])
            return JsonResponse({"status": "error parsing payload"}, status=400)
        threshold = getattr(settings, "CONTENT_INTEGRITY_FLAG_THRESHOLD", 20.0)
        ai_threshold = getattr(settings, "CONTENT_INTEGRITY_AI_FLAG_THRESHOLD", 50.0)

        check.score = result.score
        check.matched_sources = result.matched_sources
        check.ai_score = result.ai_generated_likelihood
        check.grammar_score = result.grammar_score
        check.readability_text = result.readability_text
        
        flag_reasons = []
        if check.score >= threshold:
            flag_reasons.append("plagiarism")
        if check.ai_score is not None and check.ai_score >= ai_threshold:
            flag_reasons.append("ai_generated")
            
        check.flag_reasons = flag_reasons
        check.status = ContentCheckStatus.FLAGGED if flag_reasons else ContentCheckStatus.CLEAN
        check.last_checked_at = timezone.now()
        check.error_message = ""
        check.save(update_fields=[
            "score", "matched_sources", "ai_score", "grammar_score", 
            "readability_text", "flag_reasons", "status", "last_checked_at", 
            "error_message", "updated_at"
        ])

        log.info("[content_integrity] Webhook processed for scan %s. Score: %s, Status: %s", scan_id, check.score, check.status)

        # Refresh the course report
        from ..tasks import refresh_course_report
        refresh_course_report.delay(check.course_id)

        return JsonResponse({"status": "success"})
