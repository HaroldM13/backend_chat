"""
Esquemas Pydantic para autenticación (registro y login).
"""
from pydantic import BaseModel, Field


class RegistroSchema(BaseModel):
    """Datos requeridos para registrar un nuevo usuario."""
    nombre: str = Field(..., min_length=2, max_length=50, description="Nombre visible del usuario")
    telefono: str = Field(..., min_length=7, max_length=20, description="Número de teléfono único")

    model_config = {
        "json_schema_extra": {
            "example": {
                "nombre": "Juan Hernández",
                "telefono": "3001234567"
            }
        }
    }


class LoginSchema(BaseModel):
    """Datos requeridos para iniciar sesión."""
    telefono: str = Field(..., min_length=7, max_length=20, description="Número de teléfono")

    model_config = {
        "json_schema_extra": {
            "example": {
                "telefono": "3001234567"
            }
        }
    }


class TokenSchema(BaseModel):
    """Respuesta del servidor al autenticar exitosamente."""
    access_token: str
    token_type: str = "bearer"
    usuario_id: str
    nombre: str
