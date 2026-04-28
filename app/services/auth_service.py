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
    Verifica que la sesión esté activa usando Redis como cache.
    1. Busca en Redis (O(1), sin I/O de disco).
    2. Si no está en cache, consulta MongoDB y cachea el resultado.
    Esto evita una query a MongoDB en cada request y conexión WebSocket.
    """
    from app.services.redis_service import sesion_en_cache, cachear_sesion

    if await sesion_en_cache(token):
        return True

    db = get_db()
    sesion = await db.sesiones.find_one({"token": token, "activo": True})
    if sesion:
        await cachear_sesion(token)
        return True

    return False


async def invalidar_sesion(token: str) -> None:
    """Marca la sesión como inactiva en MongoDB y la elimina del cache Redis."""
    from app.services.redis_service import invalidar_sesion_cache

    db = get_db()
    await db.sesiones.update_one(
        {"token": token},
        {"$set": {"activo": False}}
    )
    await invalidar_sesion_cache(token)
