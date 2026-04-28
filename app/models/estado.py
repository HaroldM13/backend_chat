"""
Modelo de datos para la colección 'estados' en MongoDB.
Los estados duran DURACION_MINUTOS minutos y se eliminan automáticamente.
"""
from datetime import datetime, timezone, timedelta

DURACION_MINUTOS = 5


class EstadoModel:
    @staticmethod
    def nuevo(usuario_id: str, nombre_usuario: str, url_imagen: str) -> dict:
        ahora = datetime.now(timezone.utc)
        return {
            "usuario_id": usuario_id,
            "nombre_usuario": nombre_usuario,
            "url_imagen": url_imagen,
            "created_at": ahora,
            "expira_at": ahora + timedelta(minutes=DURACION_MINUTOS),
        }
