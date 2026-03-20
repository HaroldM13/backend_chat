"""
Modelo de datos para la colección 'usuarios' en MongoDB.
Representa la estructura de un documento de usuario.
"""
from datetime import datetime, timezone
from typing import Optional
from bson import ObjectId


class UsuarioModel:
    """
    Estructura de un documento de usuario en MongoDB.

    Colección: usuarios
    Campos:
        - telefono: identificador único principal
        - nombre: nombre visible en la UI
        - created_at: fecha de creación del documento
    """

    @staticmethod
    def nuevo(telefono: str, nombre: str) -> dict:
        """Crea un diccionario listo para insertar en MongoDB."""
        return {
            "telefono": telefono,
            "nombre": nombre,
            "created_at": datetime.now(timezone.utc)
        }
