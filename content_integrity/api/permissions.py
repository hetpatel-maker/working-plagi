"""
Course content + plagiarism match data shouldn't be world-readable — only
people with authoring access to that specific course should see it.

CourseStaffRole / CourseInstructorRole are long-standing, stable Open edX
APIs (common.djangoapps.student.roles) used for exactly this kind of
"does this user have course-author-level access" check elsewhere in the
platform, so this should hold up across releases better than most of the
other version-sensitive bits in this plugin.
"""
from rest_framework.permissions import BasePermission
from opaque_keys.edx.keys import CourseKey
from common.djangoapps.student.roles import CourseStaffRole, CourseInstructorRole


class IsCourseAuthor(BasePermission):
    def has_permission(self, request, view):
        course_id = view.kwargs.get("course_id")
        if not course_id or not request.user or not request.user.is_authenticated:
            return False
        try:
            course_key = CourseKey.from_string(course_id)
        except Exception:
            return False
        return (
            CourseStaffRole(course_key).has_user(request.user)
            or CourseInstructorRole(course_key).has_user(request.user)
            or request.user.is_staff
        )
