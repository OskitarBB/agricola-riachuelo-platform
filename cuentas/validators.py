# cuentas/validators.py — Misma política que la app (validatePassword, Anexo C.2 del maestro móvil):
# al menos 8 caracteres (MinimumLengthValidator), letras y números, sin espacios al inicio ni al final.
import re

from django.core.exceptions import ValidationError

LETTER = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]")
DIGIT = re.compile(r"\d")
# Celular: 9 a 15 dígitos, con «+» opcional (mismo criterio en el registro de la app y en el alta desde la web).
PHONE_RE = re.compile(r"^\+?\d{9,15}$")


class LettersAndDigitsValidator:
    def validate(self, password, user=None):
        if not LETTER.search(password) or not DIGIT.search(password):
            raise ValidationError("Debe incluir letras y números.", code="password_policy")
        if password.strip() != password:
            raise ValidationError("No debe empezar ni terminar con espacios.", code="password_policy")

    def get_help_text(self):
        return "Debe incluir letras y números, sin espacios al inicio ni al final."
