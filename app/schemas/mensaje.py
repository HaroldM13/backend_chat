"""
Esquemas Pydantic para mensajes.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class MensajeRespuesta(BaseModel):
    """Representación de un mensaje para el cliente."""
    id: str
    tipo: str
    remitente_id: str
    nombre_remitente: str
    contenido: str
    destinatario_id: Optional[str] = None
    grupo_id: Optional[str] = None
    created_at: datetime


class EnviarMensajeSchema(BaseModel):
    """Cuerpo para enviar un mensaje vía HTTP (no WebSocket)."""
    contenido: str = Field(..., min_length=1, max_length=2000)
