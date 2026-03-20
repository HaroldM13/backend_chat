"""
Servicio de autenticación: generación y verificación de tokens JWT,
y gestión de sesiones en MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from dotenv import load_dotenv
from app.database import get_db

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "clave_insegura_cambiar")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))


def crear_token(data: dict) -> str:
    """Genera un JWT firmado con los datos del payload."""
    payload = data.copy()
    expira = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload.update({"exp": expira})
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token


def verificar_token(token: str) -> Optional[dict]:
    """
    Decodifica y valida un JWT.
    Retorna el payload si es válido, None si no.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def sesion_activa(token: str) -> bool:
    """
    Verifica que la sesión exista en MongoDB y esté marcada como activa.
    Esto permite invalidar tokens en logout sin esperar su expiración.
    """
    db = get_db()
    sesion = await db.sesiones.find_one({"token": token, "activo": True})
    return sesion is not None


async def invalidar_sesion(token: str) -> None:
    """Marca la sesión como inactiva (logout)."""
    db = get_db()
    await db.sesiones.update_one(
        {"token": token},
        {"$set": {"activo": False}}
    )
