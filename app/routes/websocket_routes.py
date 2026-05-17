"""
Endpoints WebSocket con tracking de presencia en tiempo real.
Al conectar → usuario_conectado(). Al desconectar → usuario_desconectado().
Soporta: indicadores de escritura, respuestas a mensajes, mensajes auto-destructibles.
"""
import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from bson import ObjectId
from app.websocket.manager import manager
from app.services.auth_service import verificar_token, sesion_activa
from app.services.rabbit_service import publicar_mensaje
from app.services.redis_service import guardar_ultima_vez
from app.services.log_service import registrar_log
from app.models.mensaje import MensajeModel
from app.database import get_db
from app.logger import get_logger, request_id_ctx

logger = get_logger(__name__)

router = APIRouter(tags=["WebSocket (tiempo real)"])


async def _autenticar_ws(token: str) -> dict | None:
    payload = verificar_token(token)
    if not payload:
        return None
    activa = await sesion_activa(token)
    if not activa:
        return None
    return payload


async def _resolver_reply_to(db, reply_to_id: str | None) -> dict | None:
    """Resuelve el campo reply_to buscando el mensaje original en MongoDB."""
    if not reply_to_id:
        return None
    try:
        reply_msg = await db.mensajes.find_one({"_id": ObjectId(reply_to_id)})
        if not reply_msg or reply_msg.get("eliminado"):
            return None
        r_uid = reply_msg.get("remitente_id", "")
        r_nombre = "Desconocido"
        if r_uid:
            r_u = await db.usuarios.find_one({"_id": ObjectId(r_uid)})
            if r_u:
                r_nombre = r_u["nombre"]
        return {
            "id": reply_to_id,
            "contenido": reply_msg.get("contenido", ""),
            "nombre_remitente": r_nombre,
            "subtipo": reply_msg.get("subtipo"),
        }
    except Exception:
        return None


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
    await manager.usuario_conectado(usuario_id)
    logger.info("WS sala_general conectado usuario=%s", usuario_id[:8])
    try:
        while True:
            datos = await websocket.receive_text()
            try:
                msg_json = json.loads(datos)
            except json.JSONDecodeError:
                msg_json = {"contenido": datos.strip()}

            # Indicadores de escritura — no se persisten
            if msg_json.get("tipo") == "escribiendo":
                await publicar_mensaje(sala, {
                    "tipo": "escribiendo",
                    "usuario_id": usuario_id,
                    "nombre_remitente": nombre,
                })
                continue
            if msg_json.get("tipo") == "dejo_escribir":
                await publicar_mensaje(sala, {
                    "tipo": "dejo_escribir",
                    "usuario_id": usuario_id,
                })
                continue

            contenido = msg_json.get("contenido", "").strip()
            if not contenido:
                continue

            reply_to = await _resolver_reply_to(db, msg_json.get("reply_to_id"))
            expira_en = msg_json.get("expira_en")
            if isinstance(expira_en, (int, float)) and int(expira_en) > 0:
                expira_en = int(expira_en)
            else:
                expira_en = None

            rid = uuid.uuid4().hex[:8]
            token_ctx = request_id_ctx.set(rid)
            try:
                doc = MensajeModel.nuevo(
                    "sala", usuario_id, contenido,
                    reply_to=reply_to, expira_en=expira_en,
                )
                resultado = await db.mensajes.insert_one(doc)

                logger.info("WS mensaje sala_general usuario=%s", usuario_id[:8])

                ws_payload: dict = {
                    "id": str(resultado.inserted_id),
                    "tipo": "sala",
                    "remitente_id": usuario_id,
                    "nombre_remitente": nombre,
                    "contenido": contenido,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                if reply_to:
                    ws_payload["reply_to"] = reply_to
                if doc.get("expira_at"):
                    ws_payload["expira_at"] = doc["expira_at"].isoformat()

                await publicar_mensaje(sala, ws_payload)
                await registrar_log("MESSAGE_SENT", "success", "ws",
                                    usuario_id, {"sala": "general"})
            finally:
                request_id_ctx.reset(token_ctx)

    except WebSocketDisconnect:
        await manager.desconectar(websocket, sala)
        await guardar_ultima_vez(usuario_id)
        await manager.usuario_desconectado(usuario_id)
        logger.info("WS sala_general desconectado usuario=%s", usuario_id[:8])


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
    await manager.usuario_conectado(usuario_id)
    logger.info("WS privado conectado usuario=%s → dest=%s", usuario_id[:8], destinatario_id[:8])
    try:
        while True:
            datos = await websocket.receive_text()
            try:
                msg_json = json.loads(datos)
            except json.JSONDecodeError:
                msg_json = {"contenido": datos.strip()}

            if msg_json.get("tipo") == "leido":
                await publicar_mensaje(sala, {
                    "tipo": "mensajes_leidos",
                    "lector_id": usuario_id,
                    "remitente_id": destinatario_id
                })
                continue

            # Indicadores de escritura
            if msg_json.get("tipo") == "escribiendo":
                await publicar_mensaje(sala, {
                    "tipo": "escribiendo",
                    "usuario_id": usuario_id,
                    "nombre_remitente": nombre,
                })
                continue
            if msg_json.get("tipo") == "dejo_escribir":
                await publicar_mensaje(sala, {
                    "tipo": "dejo_escribir",
                    "usuario_id": usuario_id,
                })
                continue

            contenido = msg_json.get("contenido", "").strip()
            if not contenido:
                continue

            reply_to = await _resolver_reply_to(db, msg_json.get("reply_to_id"))
            expira_en = msg_json.get("expira_en")
            if isinstance(expira_en, (int, float)) and int(expira_en) > 0:
                expira_en = int(expira_en)
            else:
                expira_en = None

            rid = uuid.uuid4().hex[:8]
            token_ctx = request_id_ctx.set(rid)
            try:
                doc = MensajeModel.nuevo(
                    "privado", usuario_id, contenido,
                    destinatario_id=destinatario_id,
                    reply_to=reply_to, expira_en=expira_en,
                )
                resultado = await db.mensajes.insert_one(doc)

                logger.info("WS mensaje privado usuario=%s → dest=%s", usuario_id[:8], destinatario_id[:8])

                ws_payload = {
                    "id": str(resultado.inserted_id),
                    "tipo": "privado",
                    "remitente_id": usuario_id,
                    "nombre_remitente": nombre,
                    "destinatario_id": destinatario_id,
                    "contenido": contenido,
                    "leido": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                if reply_to:
                    ws_payload["reply_to"] = reply_to
                if doc.get("expira_at"):
                    ws_payload["expira_at"] = doc["expira_at"].isoformat()

                await publicar_mensaje(sala, ws_payload)
                await registrar_log("PRIVATE_MESSAGE_SENT", "success", "ws",
                                    usuario_id, {"destinatario_id": destinatario_id})
            finally:
                request_id_ctx.reset(token_ctx)

    except WebSocketDisconnect:
        await manager.desconectar(websocket, sala)
        await guardar_ultima_vez(usuario_id)
        await manager.usuario_desconectado(usuario_id)
        logger.info("WS privado desconectado usuario=%s", usuario_id[:8])


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
    await manager.usuario_conectado(usuario_id)
    logger.info("WS grupo=%s conectado usuario=%s", grupo_id[:8], usuario_id[:8])
    try:
        while True:
            datos = await websocket.receive_text()
            try:
                msg_json = json.loads(datos)
            except json.JSONDecodeError:
                msg_json = {"contenido": datos.strip()}

            # Indicadores de escritura
            if msg_json.get("tipo") == "escribiendo":
                await publicar_mensaje(sala, {
                    "tipo": "escribiendo",
                    "usuario_id": usuario_id,
                    "nombre_remitente": nombre,
                })
                continue
            if msg_json.get("tipo") == "dejo_escribir":
                await publicar_mensaje(sala, {
                    "tipo": "dejo_escribir",
                    "usuario_id": usuario_id,
                })
                continue

            contenido = msg_json.get("contenido", "").strip()
            if not contenido:
                continue

            reply_to = await _resolver_reply_to(db, msg_json.get("reply_to_id"))
            expira_en = msg_json.get("expira_en")
            if isinstance(expira_en, (int, float)) and int(expira_en) > 0:
                expira_en = int(expira_en)
            else:
                expira_en = None

            rid = uuid.uuid4().hex[:8]
            token_ctx = request_id_ctx.set(rid)
            try:
                doc = MensajeModel.nuevo(
                    "grupo", usuario_id, contenido,
                    grupo_id=grupo_id,
                    reply_to=reply_to, expira_en=expira_en,
                )
                resultado = await db.mensajes.insert_one(doc)

                logger.info("WS mensaje grupo=%s usuario=%s", grupo_id[:8], usuario_id[:8])

                ws_payload = {
                    "id": str(resultado.inserted_id),
                    "tipo": "grupo",
                    "remitente_id": usuario_id,
                    "nombre_remitente": nombre,
                    "grupo_id": grupo_id,
                    "contenido": contenido,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                if reply_to:
                    ws_payload["reply_to"] = reply_to
                if doc.get("expira_at"):
                    ws_payload["expira_at"] = doc["expira_at"].isoformat()

                await publicar_mensaje(sala, ws_payload)
                await registrar_log("GROUP_MESSAGE_SENT", "success", "ws",
                                    usuario_id, {"grupo_id": grupo_id})
            finally:
                request_id_ctx.reset(token_ctx)

    except WebSocketDisconnect:
        await manager.desconectar(websocket, sala)
        await guardar_ultima_vez(usuario_id)
        await manager.usuario_desconectado(usuario_id)
        logger.info("WS grupo=%s desconectado usuario=%s", grupo_id[:8], usuario_id[:8])
