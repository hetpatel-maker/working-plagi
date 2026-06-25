"""
Use this for two cases that don't come from the live publish signal:
  1. Backfilling existing courses the first time you turn this plugin on.
  2. The nightly/weekly resweep mentioned in tasks.nightly_resweep, called
     from Celery beat or cron with `./manage.py cms check_course_content <id>`.

Usage:
    python manage.py cms check_course_content course-v1:OrgX+Course+Run
"""
from django.core.management.base import BaseCommand

from content_integrity.extraction import iter_course_blocks
from content_integrity.tasks import process_block_publish


class Command(BaseCommand):
    help = "Queue content-integrity checks for every block in a course."

    def add_arguments(self, parser):
        parser.add_argument("course_id")

    def handle(self, *args, **options):
        course_id = options["course_id"]
        count = 0
        for block in iter_course_blocks(course_id):
            process_block_publish.delay(
                usage_key=block["usage_key"],
                course_id=course_id,
                block_type=block["block_type"],
            )
            count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Queued {count} blocks from {course_id} for integrity checks.")
        )
