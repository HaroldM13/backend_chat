"""
Endpoints WebSocket con tracking de presencia en tiempo real.
Al conectar → usuario_conectado(). Al desconectar → usuario_desconectado().
"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from bson import ObjectId
from app.websocket.manager import manager
from app.services.auth_service import verificar_token, sesion_activa
from app.services.rabbit_service import publicar_mensaje
from app.services.log_service import registrar_log
from app.models.mensaje import MensajeModel
from app.database import get_db

router = APIRouter(tags=["WebSocket (tiempo real)"])


async def _autenticar_ws(token: str) -> dict | None:
    payload = verificar_token(token)
    if not payload:
        return None
    activa = await sesion_activa(token)
    if not activa:
        return None
    return payload


@router.websocket("/ws/sala")
async def ws_sala_general(
    websocket: WebSocket,
    token: str = Query(..., description="JWT del usuario autenticado")
):
    payload = await _autenticar_ws(token)
    if not payload:
        await websocket.close(code=4001)
        return

    usuario_id = payload["sub"]
    sala = "sala_general"
    db = get_db()

    usuario = await db.usuarios.find_one({"_id": ObjectId(usuario_id)})
    nombre = usuario["nombre"] if usuario else "Desconocido"

    await manager.conectar(websocket, sala)
    await manager.usuario_conectado(usuario_id)      # Registrar presencia online
    try:
        while True:
            datos = await websocket.receive_text()
            try:
                msg_json = json.loads(datos)
                contenido = msg_json.get("contenido", "").strip()
            except json.JSONDecodeError:
                contenido = datos.strip()

            if not contenido:
                continue

            doc = MensajeModel.nuevo("sala", usuario_id, contenido)
            resultado = await db.mensajes.insert_one(doc)

            await publicar_mensaje(sala, {
                "id": str(resultado.inserted_id),
                "tipo": "sala",
                "remitente_id": usuario_id,
                "nombre_remitente": nombre,
                "contenido": contenido,
                "created_at": datetime.now(timezone.utc).isoformat()
            })

            await registrar_log("MESSAGE_SENT", "success", "ws",
                                usuario_id, {"sala": "general"})

    except WebSocketDisconnect:
        await manager.desconectar(websocket, sala)
        await manager.usuario_desconectado(usuario_id)  # Quitar presencia


@router.websocket("/ws/privado/{destinatario_id}")
async def ws_privado(
    websocket: WebSocket,
    destinatario_id: str,
    token: str = Query(..., description="JWT del usuario autenticado")
):
    payload = await _autenticar_ws(token)
    if not payload:
        await websocket.close(code=4001)
        return

    usuario_id = payload["sub"]
    db = get_db()

    try:
        dest = await db.usuarios.find_one({"_id": ObjectId(destinatario_id)})
    except Exception:
        await websocket.close(code=4004)
        return

    if not dest:
        await websocket.close(code=4004)
        return

    sala = manager.clave_privada(usuario_id, destinatario_id)
    usuario = await db.usuarios.find_one({"_id": ObjectId(usuario_id)})
    nombre = usuario["nombre"] if usuario else "Desconocido"

    await manager.conectar(websocket, sala)
    await manager.usuario_conectado(usuario_id)      # Registrar presencia online
    try:
        while True:
            datos = await websocket.receive_text()
            try:
                msg_json = json.loads(datos)
            except json.JSONDecodeError:
                msg_json = {"contenido": datos.strip()}

            # Soporte para evento de "marcar como leído" desde el cliente
            if msg_json.get("tipo") == "leido":
                await publicar_mensaje(sala, {
                    "tipo": "mensajes_leidos",
                    "lector_id": usuario_id,
                    "remitente_id": destinatario_id
                })
                continue

            contenido = msg_json.get("contenido", "").strip()
            if not contenido:
                continue

            doc = MensajeModel.nuevo("privado", usuario_id, contenido,
                                     destinatario_id=destinatario_id)
            resultado = await db.mensajes.insert_one(doc)

            await publicar_mensaje(sala, {
                "id": str(resultado.inserted_id),
                "tipo": "privado",
                "remitente_id": usuario_id,
                "nombre_remitente": nombre,
                "destinatario_id": destinatario_id,
                "contenido": contenido,
                "leido": False,
                "created_at": datetime.now(timezone.utc).isoformat()
            })

            await registrar_log("PRIVATE_MESSAGE_SENT", "success", "ws",
                                usuario_id, {"destinatario_id": destinatario_id})

    except WebSocketDisconnect:
        await manager.desconectar(websocket, sala)
        await manager.usuario_desconectado(usuario_id)  # Quitar presencia


@router.websocket("/ws/grupo/{grupo_id}")
async def ws_grupo(
    websocket: WebSocket,
    grupo_id: str,
    token: str = Query(..., description="JWT del usuario autenticado")
):
    payload = await _autenticar_ws(token)
    if not payload:
        await websocket.close(code=4001)
        return

    usuario_id = payload["sub"]
    db = get_db()

    try:
        grupo = await db.grupos.find_one({"_id": ObjectId(grupo_id)})
    except Exception:
        await websocket.close(code=4004)
        return

    if not grupo or usuario_id not in grupo["miembros"]:
        await websocket.close(code=4003)
        return

    sala = manager.clave_grupo(grupo_id)
    usuario = await db.usuarios.find_one({"_id": ObjectId(usuario_id)})
    nombre = usuario["nombre"] if usuario else "Desconocido"

    await manager.conectar(websocket, sala)
    await manager.usuario_conectado(usuario_id)      # Registrar presencia online
    try:
        while True:
            datos = await websocket.receive_text()
            try:
                msg_json = json.loads(datos)
                contenido = msg_json.get("contenido", "").strip()
            except json.JSONDecodeError:
                contenido = datos.strip()

            if not contenido:
                continue

            doc = MensajeModel.nuevo("grupo", usuario_id, contenido, grupo_id=grupo_id)
            resultado = await db.mensajes.insert_one(doc)

            await publicar_mensaje(sala, {
                "id": str(resultado.inserted_id),
                "tipo": "grupo",
                "remitente_id": usuario_id,
                "nombre_remitente": nombre,
                "grupo_id": grupo_id,
                "contenido": contenido,
                "created_at": datetime.now(timezone.utc).isoformat()
            })

            await registrar_log("GROUP_MESSAGE_SENT", "success", "ws",
                                usuario_id, {"grupo_id": grupo_id})

    except WebSocketDisconnect:
        await manager.desconectar(websocket, sala)
        await manager.usuario_desconectado(usuario_id)  # Quitar presencia
