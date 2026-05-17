"""
Endpoints para reacciones a mensajes con toggle (agregar/quitar).
Colección: reacciones { mensaje_id, usuario_id, emoji }
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from bson import ObjectId
from app.middleware.auth_middleware import obtener_usuario_actual
from app.database import get_db
from app.services.rabbit_service import publicar_mensaje
from app.websocket.manager import manager

router = APIRouter(prefix="/reacciones", tags=["Reacciones"])

EMOJIS_VALIDOS = {'👍', '❤️', '😂', '😮', '😢', '🔥', '👏', '🎉'}


class ReaccionPayload(BaseModel):
    emoji: str


async def _reacciones_de_mensaje(db, mensaje_id: str) -> list:
    """Agrupa las reacciones de un mensaje por emoji con conteo y lista de usuarios."""
    pipeline = [
        {"$match": {"mensaje_id": mensaje_id}},
        {"$group": {
            "_id": "$emoji",
            "count": {"$sum": 1},
            "usuarios": {"$push": "$usuario_id"},
        }},
        {"$project": {"emoji": "$_id", "count": 1, "usuarios": 1, "_id": 0}},
    ]
    return await db.reacciones.aggregate(pipeline).to_list(None)


def _sala_msg(msg: dict) -> str:
    """Devuelve la clave de sala RabbitMQ a partir del documento de mensaje."""
    tipo = msg.get("tipo", "sala")
    if tipo == "sala":
        return "sala_general"
    if tipo == "privado":
        return manager.clave_privada(
            msg.get("remitente_id", ""),
            msg.get("destinatario_id", ""),
        )
    if tipo == "grupo":
        return manager.clave_grupo(msg.get("grupo_id", ""))
    return "sala_general"


@router.post("/{mensaje_id}", status_code=200)
async def toggle_reaccion(
    mensaje_id: str,
    payload: ReaccionPayload,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """Alterna la reacción de un usuario en un mensaje (agrega si no existe, quita si ya existe)."""
    if payload.emoji not in EMOJIS_VALIDOS:
        raise HTTPException(status_code=400, detail="Emoji no permitido")

    db = get_db()
    usuario_id = usuario_actual["sub"]

    try:
        msg = await db.mensajes.find_one({"_id": ObjectId(mensaje_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="ID de mensaje inválido")

    if not msg:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
    if msg.get("eliminado"):
        raise HTTPException(status_code=400, detail="No se puede reaccionar a un mensaje eliminado")

    existente = await db.reacciones.find_one({
        "mensaje_id": mensaje_id,
        "usuario_id": usuario_id,
        "emoji": payload.emoji,
    })

    if existente:
        await db.reacciones.delete_one({"_id": existente["_id"]})
    else:
        await db.reacciones.insert_one({
            "mensaje_id": mensaje_id,
            "usuario_id": usuario_id,
            "emoji": payload.emoji,
        })

    reacciones = await _reacciones_de_mensaje(db, mensaje_id)
    sala = _sala_msg(msg)
    await publicar_mensaje(sala, {
        "tipo": "reaccion",
        "mensaje_id": mensaje_id,
        "reacciones": reacciones,
    })
    return {"reacciones": reacciones}
