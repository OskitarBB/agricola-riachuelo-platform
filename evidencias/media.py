# evidencias/media.py — URLs firmadas de Cloudinary para la web (W-10, DW-26). Nunca se guardan en la base de datos.
# Contrato de la sección 12 del Maestro Web: signed_image_url(capture, variant) con variantes miniatura, revision y
# original. La implementación (Cloudinary real o simulado de desarrollo) vive en evidencias/nube.py.
from evidencias.nube import VARIANTS, signed_image_url

__all__ = ["VARIANTS", "signed_image_url"]
