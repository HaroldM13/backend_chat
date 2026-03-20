"""
Modelo de datos para la colección 'sesiones' en MongoDB.
Se usa para rastrear y invalidar tokens JWT activos.
"""
from datetime import datetime, timezone


class SesionModel:
    """
    Representa una sesión activa de usuario.

    Colección: sesiones
    """

    @staticmethod
    def nueva(usuario_id: str, token: str) -> dict:
        """Crea un diccionario listo para insertar en MongoDB."""
        return {
            "usuario_id": usuario_id,
            "token": token,
            "activo": True,
            "created_at": datetime.now(timezone.utc)
        }
