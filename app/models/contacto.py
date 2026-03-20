"""
Modelo de datos para la colección 'contactos' en MongoDB.
"""
from datetime import datetime, timezone


class ContactoModel:
    """
    Relación entre dos usuarios (usuario guarda a contacto).

    Colección: contactos
    """

    @staticmethod
    def nuevo(usuario_id: str, contacto_id: str) -> dict:
        """Crea un diccionario listo para insertar en MongoDB."""
        return {
            "usuario_id": usuario_id,
            "contacto_id": contacto_id,
            "created_at": datetime.now(timezone.utc)
        }
