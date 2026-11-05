# notificaciones/errores.py — Error común de los canales de aviso (Telegram, v1.5 ADR-W-011).


class AvisoError(Exception):
    """Falla al enviar un aviso. retryable=False: no se reintenta solo (token inválido, chat inexistente, etc.)."""

    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable
