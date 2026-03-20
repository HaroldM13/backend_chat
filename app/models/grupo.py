"""
Modelo de datos para la colección 'grupos' en MongoDB.
"""
from datetime import datetime, timezone
from typing import List


class GrupoModel:
    """
    Representa un grupo de chat.

    Colección: grupos
    """

    @staticmethod
    def nuevo(nombre: str, creador_id: str, miembros: List[str]) -> dict:
        """Crea un diccionario listo para insertar en MongoDB."""
        return {
            "nombre": nombre,
            "creador_id": creador_id,
            "miembros": miembros,  # lista de user_id como strings
            "created_at": datetime.now(timezone.utc)
        }
