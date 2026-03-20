"""
Modelo de datos para la colección 'logs' en MongoDB.
Auditoría completa de todas las acciones del sistema.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any


class LogModel:
    """
    Registro de auditoría del sistema.

    Colección: logs
    Acciones registradas:
        USER_REGISTER, USER_LOGIN, USER_LOGOUT, USER_DELETED,
        MESSAGE_SENT, PRIVATE_MESSAGE_SENT, GROUP_MESSAGE_SENT,
        GROUP_CREATED, GROUP_DELETED, GROUP_MEMBER_ADDED, GROUP_LEFT,
        CONTACT_ADDED, CONTACT_DELETED, ERROR
    """

    @staticmethod
    def nuevo(
        action: str,
        status: str,
        ip: str,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> dict:
        """Crea un diccionario listo para insertar en MongoDB."""
        return {
            "action": action,
            "user_id": user_id,
            "ip": ip,
            "status": status,          # 'success' | 'error'
            "details": details or {},
            "created_at": datetime.now(timezone.utc)
        }
