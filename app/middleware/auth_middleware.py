"""
Dependencia de autenticación para proteger endpoints con JWT.
Se usa como dependencia de FastAPI: Depends(obtener_usuario_actual)
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.services.auth_service import verificar_token, sesion_activa
from app.database import get_db

# Esquema Bearer para leer el token del header Authorization
esquema_bearer = HTTPBearer()


async def obtener_usuario_actual(
    credenciales: HTTPAuthorizationCredentials = Depends(esquema_bearer)
) -> dict:
    """
    Extrae y valida el JWT del header Authorization.
    Retorna el payload del token si es válido y la sesión está activa.
    Lanza 401 en cualquier caso de fallo.
    """
    token = credenciales.credentials

    # Verificar firma y expiración del token
    payload = verificar_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado"
        )

    # Verificar que la sesión no haya sido invalidada (logout)
    activa = await sesion_activa(token)
    if not activa:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión inválida o cerrada"
        )

    # Adjuntar el token al payload para poder invalidarlo en logout
    payload["_token"] = token
    return payload
