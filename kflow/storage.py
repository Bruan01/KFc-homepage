# pyright: reportMissingImports=false, reportMissingModuleSource=false
from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class LenientManifestStaticFilesStorage(ManifestStaticFilesStorage):
    """Use hashed production assets while keeping local runs usable before collectstatic."""

    manifest_strict = False

    def stored_name(self, name):
        try:
            return super().stored_name(name)
        except ValueError:
            return name
