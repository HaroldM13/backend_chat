"""
Endpoints HTTP para historial, marcar como leído y eliminar conversación privada.
"""
from fastapi import APIRouter, HTTPException, status, Depends, Query, Request
from bson import ObjectId
from app.middleware.auth_middleware import obtener_usuario_actual
from app.websocket.manager import manager
from app.database import get_db

router = APIRouter(prefix="/mensajes", tags=["Mensajes"])


async def _enriquecer_mensajes(db, mensajes: list) -> list:
    """Agrega nombre del remitente y normaliza campos a cada mensaje."""
    resultado = []
    cache: dict = {}

    for msg in mensajes:
        rid = msg.get("remitente_id")
        if rid not in cache:
            u = await db.usuarios.find_one({"_id": ObjectId(rid)})
            cache[rid] = u["nombre"] if u else "Usuario eliminado"

        resultado.append({
            "id": str(msg["_id"]),
            "tipo": msg["tipo"],
            "remitente_id": rid,
            "nombre_remitente": cache[rid],
            "contenido": msg["contenido"],
            "destinatario_id": msg.get("destinatario_id"),
            "grupo_id": msg.get("grupo_id"),
            "leido": msg.get("leido"),   # None para sala/grupo, bool para privados
            "created_at": msg["created_at"]
        })

    return resultado


@router.get("/sala", summary="Historial sala general")
async def historial_sala(
    limite: int = Query(50, ge=1, le=100),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    db = get_db()
    mensajes = await db.mensajes.find(
        {"tipo": "sala"}
    ).sort("created_at", 1).limit(limite).to_list(length=None)
    return await _enriquecer_mensajes(db, mensajes)


@router.get("/privado/{otro_usuario_id}", summary="Historial de chat privado")
async def historial_privado(
    otro_usuario_id: str,
    limite: int = Query(50, ge=1, le=100),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    db = get_db()
    usuario_id = usuario_actual["sub"]

    filtro = {
        "tipo": "privado",
        "$or": [
            {"remitente_id": usuario_id, "destinatario_id": otro_usuario_id},
            {"remitente_id": otro_usuario_id, "destinatario_id": usuario_id}
        ]
    }
    mensajes = await db.mensajes.find(filtro).sort("created_at", 1).limit(limite).to_list(length=None)
    return await _enriquecer_mensajes(db, mensajes)


@router.post(
    "/privado/{otro_usuario_id}/leer",
    status_code=status.HTTP_200_OK,
    summary="Marcar mensajes como leídos",
    description=(
        "Marca como leídos todos los mensajes recibidos del otro usuario. "
        "También emite un evento WebSocket para que el remitente vea los ✓✓."
    )
)
async def marcar_leidos(
    otro_usuario_id: str,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Marca mensajes del otro usuario hacia mí como leídos y notifica por WS."""
    db = get_db()
    usuario_id = usuario_actual["sub"]

    # Marcar como leídos solo los mensajes donde YO soy el destinatario
    resultado = await db.mensajes.update_many(
        {
            "tipo": "privado",
            "remitente_id": otro_usuario_id,
            "destinatario_id": usuario_id,
            "leido": False
        },
        {"$set": {"leido": True}}
    )

    # Notificar al remitente por WebSocket que sus mensajes fueron leídos
    if resultado.modified_count > 0:
        sala = manager.clave_privada(usuario_id, otro_usuario_id)
        await manager.broadcast(sala, {
            "tipo": "mensajes_leidos",
            "lector_id": usuario_id,
            "remitente_id": otro_usuario_id
        })

    return {"leidos": resultado.modified_count}


@router.delete(
    "/privado/{otro_usuario_id}",
    status_code=status.HTTP_200_OK,
    summary="Eliminar conversación privada",
    description=(
        "Elimina todos los mensajes privados entre el usuario autenticado y otro. "
        "Afecta a ambos usuarios. No elimina el contacto."
    )
)
async def eliminar_chat_privado(
    otro_usuario_id: str,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Elimina la conversación privada para ambos usuarios."""
    db = get_db()
    usuario_id = usuario_actual["sub"]

    resultado = await db.mensajes.delete_many({
        "tipo": "privado",
        "$or": [
            {"remitente_id": usuario_id, "destinatario_id": otro_usuario_id},
            {"remitente_id": otro_usuario_id, "destinatario_id": usuario_id}
        ]
    })

    return {
        "mensaje": "Conversación eliminada para ambos usuarios",
        "mensajes_eliminados": resultado.deleted_count
    }


@router.get("/grupo/{grupo_id}", summary="Historial de mensajes de grupo")
async def historial_grupo(
    grupo_id: str,
    limite: int = Query(50, ge=1, le=100),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    db = get_db()
    usuario_id = usuario_actual["sub"]

    try:
        grupo = await db.grupos.find_one({"_id": ObjectId(grupo_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="ID de grupo inválido")

    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    if usuario_id not in grupo["miembros"]:
        raise HTTPException(status_code=403, detail="No eres miembro de este grupo")

    mensajes = await db.mensajes.find(
        {"tipo": "grupo", "grupo_id": grupo_id}
    ).sort("created_at", 1).limit(limite).to_list(length=None)

    return await _enriquecer_mensajes(db, mensajes)
