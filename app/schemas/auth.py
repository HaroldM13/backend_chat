"""
Esquemas Pydantic para autenticación (registro y login con OTP).
"""
from pydantic import BaseModel, Field


class EnviarOTPSchema(BaseModel):
    """Solicitud de envío de código OTP al teléfono."""
    telefono: str = Field(..., min_length=7, max_length=20, description="Número de teléfono")

    model_config = {
        "json_schema_extra": {
            "example": {"telefono": "3001234567"}
        }
    }


class RegistroSchema(BaseModel):
    """Datos requeridos para registrar un nuevo usuario."""
    nombre: str = Field(..., min_length=2, max_length=50, description="Nombre visible del usuario")
    telefono: str = Field(..., min_length=7, max_length=20, description="Número de teléfono único")
    codigo: str = Field(default="", max_length=10, description="Código OTP (opcional si REQUIRE_OTP=false)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "nombre": "Juan Hernández",
                "telefono": "3001234567",
                "codigo": "123456"
            }
        }
    }


class LoginSchema(BaseModel):
    """Datos requeridos para iniciar sesión (solo teléfono)."""
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
