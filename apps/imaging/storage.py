"""Private storage for provider originals; never expose a media URL."""
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class OriginalImageStorage(FileSystemStorage):
    @property
    def base_location(self):
        return Path(getattr(settings, "IMAGING_ORIGINAL_ROOT", settings.BASE_DIR / "data" / "imaging-originals"))

    @property
    def location(self):
        return str(self.base_location.resolve())

    def url(self, name):
        """Reject public links: originals require a paid authenticated request."""
        raise ValueError("原图仅可通过付费下载接口访问")


def original_upload_to(instance, filename):
    """Keep the actual provider format independently of the preview format."""
    extension = Path(filename).suffix
    return f"{instance.user_id}/{instance.created_at:%Y/%m}/{instance.id}{extension}"
