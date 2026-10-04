"""Cloudinary URL helpers.

Only Django signs URLs. Templates receive already-safe thumbnail/revision URLs,
and the original is exposed only when a view intentionally asks for it.
"""
from django.conf import settings
from cloudinary.utils import cloudinary_url


TRANSFORMS = {
    "thumb": [{"width": 320, "height": 220, "crop": "fill", "quality": "auto", "fetch_format": "auto"}],
    "revision": [{"width": 1280, "crop": "limit", "quality": "auto", "fetch_format": "auto"}],
    "original": [],
}


def signed_capture_url(capture, kind="revision"):
    """Return a signed Cloudinary URL or an empty string when media is missing."""
    if not capture or not capture.cloudinary_public_id or not settings.CLOUDINARY_URL:
        return ""
    options = {"sign_url": True, "secure": True, "transformation": TRANSFORMS.get(kind, TRANSFORMS["revision"])}
    if capture.cloudinary_version:
        options["version"] = capture.cloudinary_version
    try:
        url, _ = cloudinary_url(capture.cloudinary_public_id, **options)
    except ValueError:
        return ""
    return url
