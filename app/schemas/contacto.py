"""
Esquemas Pydantic para contactos.
"""
from pydantic import BaseModel, Field
from datetime import datetime


class AgregarContactoSchema(BaseModel):
    """Datos para agregar un contacto por número de teléfono."""
    telefono: str = Field(..., min_length=7, max_length=20, description="Teléfono del contacto")

    model_config = {
        "json_schema_extra": {
            "example": {"telefono": "3009876543"}
        }
    }


class ContactoRespuesta(BaseModel):
    """Información de un contacto en la lista."""
    contacto_id: str
    nombre: str
    telefono: str
    created_at: datetime
