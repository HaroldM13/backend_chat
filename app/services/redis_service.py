"""
Servicio Redis: cache de sesiones activas y tracking de presencia de usuarios.

- Sesiones: evita consultar MongoDB en cada request autenticado.
  Clave: sesion:{token} → "1"  con TTL igual al del JWT.

- Presencia: reemplaza el dict in-memory con operaciones atómicas INCR/DECR.
  Clave: presencia:{usuario_id} → contador de conexiones WS activas.
  Un usuario puede tener múltiples pestañas abiertas; cuando el contador
  llega a 0 la clave se elimina y el usuario queda offline.
"""
import os
from typing import Optional
import redis.asyncio as aioredis

_cliente: Optional[aioredis.Redis] = None

# TTL del cache de sesión: igual que la expiración del JWT
SESION_TTL = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")) * 60


async def conectar_redis() -> None:
    global _cliente
    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    _cliente = aioredis.from_url(url, decode_responses=True)


async def cerrar_redis() -> None:
    global _cliente
    if _cliente:
        await _cliente.aclose()
        _cliente = None


def get_redis() -> aioredis.Redis:
    if _cliente is None:
        raise RuntimeError("Redis no está conectado")
    return _cliente


# ── Cache de sesiones ────────────────────────────────────────────────────────

async def cachear_sesion(token: str) -> None:
    """Guarda el token como sesión activa en Redis con TTL."""
    await get_redis().setex(f"sesion:{token}", SESION_TTL, "1")


async def sesion_en_cache(token: str) -> bool:
    """Retorna True si el token está en el cache Redis (sesión activa)."""
    val = await get_redis().get(f"sesion:{token}")
    return val is not None


async def invalidar_sesion_cache(token: str) -> None:
    """Elimina el token del cache Redis al hacer logout."""
    await get_redis().delete(f"sesion:{token}")


# ── Presencia ────────────────────────────────────────────────────────────────

async def marcar_online(usuario_id: str) -> None:
    """Incrementa el contador de conexiones WS activas del usuario."""
    await get_redis().incr(f"presencia:{usuario_id}")


async def marcar_offline(usuario_id: str) -> None:
    """Decrementa el contador; elimina la clave cuando llega a 0 (offline)."""
    key = f"presencia:{usuario_id}"
    r = get_redis()
    nuevo = await r.decr(key)
    if nuevo <= 0:
        await r.delete(key)


async def esta_online(usuario_id: str) -> bool:
    """Retorna True si el usuario tiene al menos una conexión WS activa."""
    val = await get_redis().get(f"presencia:{usuario_id}")
    return int(val or 0) > 0
