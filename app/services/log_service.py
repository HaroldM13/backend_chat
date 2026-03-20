"""
Servicio de logs de auditoría.
Registra todas las acciones importantes del sistema en la colección 'logs'.
"""
from typing import Optional, Dict, Any
from app.models.log import LogModel
from app.database import get_db


async def registrar_log(
    action: str,
    status: str,
    ip: str,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
) -> None:
    """
    Inserta un documento de auditoría en la colección 'logs'.

    Acciones válidas:
        USER_REGISTER, USER_LOGIN, USER_LOGOUT, USER_DELETED,
        MESSAGE_SENT, PRIVATE_MESSAGE_SENT, GROUP_MESSAGE_SENT,
        GROUP_CREATED, GROUP_DELETED, GROUP_MEMBER_ADDED, GROUP_LEFT,
        CONTACT_ADDED, CONTACT_DELETED, ERROR
    """
    db = get_db()
    documento = LogModel.nuevo(
        action=action,
        status=status,
        ip=ip,
        user_id=user_id,
        details=details
    )
    # Inserción no bloqueante gracias a Motor
    await db.logs.insert_one(documento)
