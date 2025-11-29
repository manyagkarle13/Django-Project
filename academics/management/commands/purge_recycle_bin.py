# academics/management/commands/purge_recycle_bin.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
import logging
import os
from django.db import models as djmodels

from academics.models import CollegeLevelCourse, SemesterCredit, Syllabus

logger = logging.getLogger(__name__)

# Models to purge (add more if needed)
TARGETS = [CollegeLevelCourse, SemesterCredit, Syllabus]

# Common candidate timestamp fields (we'll pick the first that exists)
COMMON_TIMESTAMP_FIELDS = ("deleted_at", "deleted_on", "removed_at", "deleted", "deleted_date")

# Common soft-delete flag names to check
COMMON_FLAG_FIELDS = ("is_deleted", "deleted", "is_removed")


def _find_flag_field(model):
    """
    Return the name of the boolean 'deleted' flag field if present, else None.
    Checks COMMON_FLAG_FIELDS for a BooleanField.
    """
    for fname in COMMON_FLAG_FIELDS:
        try:
            f = model._meta.get_field(fname)
        except Exception:
            continue
        if isinstance(f, djmodels.BooleanField):
            return fname
    return None


def _find_timestamp_field(model):
    """
    Return the name of a DateTimeField used for deletion timestamp, else None.
    Checks COMMON_TIMESTAMP_FIELDS in order and ensures the field is a DateTimeField.
    """
    for fname in COMMON_TIMESTAMP_FIELDS:
        try:
            f = model._meta.get_field(fname)
        except Exception:
            continue
        # Ensure it's a DateTimeField (safe guard)
        if isinstance(f, djmodels.DateTimeField) or getattr(f, 'get_internal_type', lambda: None)() == 'DateTimeField':
            return fname
    return None


def model_file_fields(model):
    """Return a list of FileField/ImageField names present on the model."""
    file_fields = []
    for f in model._meta.get_fields():
        # avoid related/ManyToMany fields
        if getattr(f, "get_internal_type", lambda: "")() in ("FileField", "ImageField"):
            file_fields.append(f.name)
    return file_fields


class Command(BaseCommand):
    help = "Permanently delete objects that were soft-deleted more than N days ago."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Permanently delete items soft-deleted more than this many days ago (default: 30).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not delete anything; only log what would be deleted.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=days)

        self.stdout.write(self.style.NOTICE(f"Purging items soft-deleted before {cutoff.isoformat()} (dry_run={dry_run})"))

        total_deleted = 0
        for model in TARGETS:
            file_fields = model_file_fields(model)

            # choose boolean flag field (e.g. is_deleted / deleted)
            flag_field = _find_flag_field(model)
            if not flag_field:
                logger.info("No boolean deleted flag field found for %s — skipping purge for this model.", model.__name__)
                continue

            # build base queryset: only soft-deleted items
            qs = model.objects.filter(**{flag_field: True})

            # find a timestamp field (deleted_at / deleted_on / removed_at etc.)
            ts_field = _find_timestamp_field(model)
            if ts_field:
                # only purge items soft-deleted before cutoff when a proper datetime field exists
                try:
                    qs = qs.filter(**{f"{ts_field}__lte": cutoff})
                except Exception as e:
                    logger.exception("Failed filtering %s by timestamp field '%s': %s", model.__name__, ts_field, e)
                    continue
            else:
                # If a timestamp field doesn't exist, we should NOT attempt datetime filtering.
                logger.info("No datetime timestamp field for %s — purge will delete all soft-deleted rows for this model (if confirmed).", model.__name__)
                # Optionally skip such models to be safe:
                # continue

            count = qs.count()
            if count == 0:
                self.stdout.write(self.style.SUCCESS(f"No old soft-deleted {model.__name__} items to purge."))
                continue

            self.stdout.write(self.style.WARNING(f"Found {count} {model.__name__} objects to purge."))

            if dry_run:
                for obj in qs:
                    self.stdout.write(f"[DRY] Would delete {model.__name__} pk={obj.pk}")
                continue

            # Delete files on disk for FileField/ImageField on each object (best-effort)
            deleted_here = 0
            with transaction.atomic():
                for obj in qs:
                    try:
                        # remove attached files
                        for fname in file_fields:
                            try:
                                fval = getattr(obj, fname, None)
                                if not fval:
                                    continue
                                # If file storage has path and file exists, remove
                                # Use .path only if storage supports it
                                try:
                                    file_path = fval.path
                                except Exception:
                                    file_path = None
                                if file_path and os.path.exists(file_path):
                                    try:
                                        os.remove(file_path)
                                        logger.info("Removed file: %s", file_path)
                                    except Exception:
                                        logger.exception("Failed to remove file: %s", file_path)

                                # clear field in case of signals or cascade
                                fval.delete(save=False)
                            except Exception:
                                logger.exception("Error while removing file field %s on %s(%s)", fname, model.__name__, obj.pk)

                        # finally delete the object itself
                        obj.delete()
                        deleted_here += 1
                    except Exception:
                        logger.exception("Failed to permanently delete %s pk=%s", model.__name__, getattr(obj, "pk", "?"))

            total_deleted += deleted_here
            self.stdout.write(self.style.SUCCESS(f"Permanently deleted {deleted_here} {model.__name__} objects."))

        self.stdout.write(self.style.SUCCESS(f"Done. Total permanently deleted: {total_deleted}"))
