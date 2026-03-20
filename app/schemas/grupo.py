"""
Esquemas Pydantic para grupos.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List


class CrearGrupoSchema(BaseModel):
    """Datos para crear un nuevo grupo."""
    nombre: str = Field(..., min_length=2, max_length=60, description="Nombre del grupo")

    model_config = {
        "json_schema_extra": {
            "example": {"nombre": "Proyecto Final"}
        }
    }


class AgregarMiembroSchema(BaseModel):
    """Datos para agregar un miembro al grupo por teléfono."""
    telefono: str = Field(..., min_length=7, max_length=20)

    model_config = {
        "json_schema_extra": {
            "example": {"telefono": "3001234567"}
        }
    }


class MiembroInfo(BaseModel):
    """Información básica de un miembro del grupo."""
    id: str
    nombre: str
    telefono: str


class GrupoRespuesta(BaseModel):
    """Información completa de un grupo."""
    id: str
    nombre: str
    creador_id: str
    miembros: List[MiembroInfo]
    created_at: datetime
