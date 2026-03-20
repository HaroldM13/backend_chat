"""
Esquemas Pydantic para respuestas relacionadas con usuarios.
"""
from pydantic import BaseModel
from datetime import datetime


class UsuarioRespuesta(BaseModel):
    """Representación pública de un usuario (sin datos sensibles)."""
    id: str
    nombre: str
    telefono: str
    created_at: datetime
