"""
Modelo de datos para la colección 'mensajes' en MongoDB.
Los mensajes pueden ser de sala general, privados o de grupo.
"""
from datetime import datetime, timezone
from typing import Optional


class MensajeModel:
    """
    Representa un mensaje en el sistema.

    Colección: mensajes
    Tipos:
        - 'sala': mensaje en la sala general
        - 'privado': mensaje entre dos usuarios
        - 'grupo': mensaje dentro de un grupo
    """

    @staticmethod
    def nuevo(
        tipo: str,
        remitente_id: str,
        contenido: str,
        destinatario_id: Optional[str] = None,
        grupo_id: Optional[str] = None,
        subtipo: Optional[str] = None,
    ) -> dict:
        """Crea un diccionario listo para insertar en MongoDB."""
        doc = {
            "tipo": tipo,           # 'sala' | 'privado' | 'grupo'
            "remitente_id": remitente_id,
            "contenido": contenido,
            "created_at": datetime.now(timezone.utc)
        }
        if destinatario_id:
            doc["destinatario_id"] = destinatario_id
        if grupo_id:
            doc["grupo_id"] = grupo_id
        if subtipo:
            doc["subtipo"] = subtipo  # 'imagen' para mensajes con imagen
        return doc
