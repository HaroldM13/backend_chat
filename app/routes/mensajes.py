"""
Endpoints HTTP para historial, marcar como leído, eliminar conversación e imágenes.
Incluye edición y eliminación suave de mensajes propios.
"""
import asyncio
import io
import uuid
import pathlib
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends, Query, Request, UploadFile, File, Form
from pydantic import BaseModel, Field
from PIL import Image
from bson import ObjectId
from app.middleware.auth_middleware import obtener_usuario_actual
from app.websocket.manager import manager
from app.services.rabbit_service import publicar_mensaje
from app.models.mensaje import MensajeModel
from app.database import get_db
from app.logger import get_logger

logger = get_logger(__name__)

UPLOADS_CHAT = pathlib.Path("uploads/chat")

router = APIRouter(prefix="/mensajes", tags=["Mensajes"])


class EditarMensajeSchema(BaseModel):
    contenido: str = Field(..., min_length=1, max_length=4000)


async def _ultimo_mensaje_formateado(db, filtro: dict) -> dict | None:
    """Devuelve el último mensaje (más reciente) que cumpla el filtro, formateado."""
    msgs = await db.mensajes.find(filtro).sort("created_at", -1).limit(1).to_list(1)
    if not msgs:
        return None
    msg = msgs[0]
    rid = msg.get("remitente_id", "")
    nombre = "Usuario eliminado"
    if rid:
        try:
            u = await db.usuarios.find_one({"_id": ObjectId(rid)})
            if u:
                nombre = u["nombre"]
        except Exception:
            pass
    subtipo = msg.get("subtipo")
    contenido = msg.get("contenido", "")
    if msg.get("eliminado"):
        contenido = "🗑️ Mensaje eliminado"
    elif subtipo == "imagen":
        contenido = "📷 Imagen"
    elif subtipo == "audio":
        contenido = "🎵 Audio"
    elif subtipo == "video":
        contenido = "🎬 Video"
    elif subtipo == "archivo":
        contenido = "📎 Archivo"
    elif subtipo == "encuesta":
        contenido = "📊 Encuesta"
    return {
        "nombre_remitente": nombre,
        "remitente_id": rid,
        "contenido": contenido,
        "subtipo": subtipo,
        "created_at": msg.get("created_at"),
    }


async def _enriquecer_mensajes(db, mensajes: list) -> list:
    """Agrega nombre del remitente, reacciones y normaliza campos a cada mensaje."""
    if not mensajes:
        return []

    resultado = []
    cache: dict = {}

    # Recopilar IDs para batch query de reacciones
    msg_ids = [str(msg["_id"]) for msg in mensajes]

    # Batch: reacciones agrupadas por mensaje
    pipeline_reacciones = [
        {"$match": {"mensaje_id": {"$in": msg_ids}}},
        {"$group": {
            "_id": {"mensaje_id": "$mensaje_id", "emoji": "$emoji"},
            "count": {"$sum": 1},
            "usuarios": {"$push": "$usuario_id"},
        }},
        {"$project": {
            "mensaje_id": "$_id.mensaje_id",
            "emoji": "$_id.emoji",
            "count": 1,
            "usuarios": 1,
            "_id": 0,
        }},
    ]
    raw_reacciones = await db.reacciones.aggregate(pipeline_reacciones).to_list(None)
    reacciones_map: dict = {}
    for r in raw_reacciones:
        mid = r["mensaje_id"]
        if mid not in reacciones_map:
            reacciones_map[mid] = []
        reacciones_map[mid].append({
            "emoji": r["emoji"],
            "count": r["count"],
            "usuarios": r["usuarios"],
        })

    # Batch: votos de encuesta
    votos_raw = await db.votos_encuesta.find({"mensaje_id": {"$in": msg_ids}}).to_list(None)
    votos_map: dict = {}
    for v in votos_raw:
        mid = v["mensaje_id"]
        if mid not in votos_map:
            votos_map[mid] = {}
        oid = v["opcion_id"]
        votos_map[mid][oid] = votos_map[mid].get(oid, 0) + 1

    for msg in mensajes:
        rid = msg.get("remitente_id")
        if rid not in cache:
            try:
                u = await db.usuarios.find_one({"_id": ObjectId(rid)})
                cache[rid] = u["nombre"] if u else "Usuario eliminado"
            except Exception:
                cache[rid] = "Usuario eliminado"

        msg_id = str(msg["_id"])
        expira_at = msg.get("expira_at")

        resultado.append({
            "id": msg_id,
            "tipo": msg["tipo"],
            "subtipo": msg.get("subtipo"),
            "nombre_archivo": msg.get("nombre_archivo"),
            "remitente_id": rid,
            "nombre_remitente": cache[rid],
            "contenido": msg["contenido"],
            "destinatario_id": msg.get("destinatario_id"),
            "grupo_id": msg.get("grupo_id"),
            "leido": msg.get("leido"),
            "created_at": msg["created_at"],
            "editado": msg.get("editado", False),
            "eliminado": msg.get("eliminado", False),
            "reply_to": msg.get("reply_to"),
            "reacciones": reacciones_map.get(msg_id, []),
            "expira_at": expira_at.isoformat() if expira_at else None,
            "votos": votos_map.get(msg_id) if msg.get("subtipo") == "encuesta" else None,
        })

    return resultado


@router.get("/resumen", summary="Último mensaje por conversación")
async def resumen_conversaciones(
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Devuelve el último mensaje de cada conversación del usuario (sala, privados, grupos)."""
    db = get_db()
    usuario_id = usuario_actual["sub"]
    resultado: dict = {}

    # Sala general
    sala = await _ultimo_mensaje_formateado(db, {"tipo": "sala"})
    if sala:
        resultado["sala"] = sala

    # Privados — paralelo por contacto
    contactos = await db.contactos.find({"usuario_id": usuario_id}).to_list(None)

    async def res_privado_con_noLeidos(contact_id: str):
        filtro_priv = {
            "tipo": "privado",
            "$or": [
                {"remitente_id": usuario_id, "destinatario_id": contact_id},
                {"remitente_id": contact_id, "destinatario_id": usuario_id},
            ],
        }
        r, no_leidos = await asyncio.gather(
            _ultimo_mensaje_formateado(db, filtro_priv),
            db.mensajes.count_documents({
                "tipo": "privado",
                "remitente_id": contact_id,
                "destinatario_id": usuario_id,
                "leido": False,
            })
        )
        return contact_id, r, int(no_leidos)

    for cid, r, no_leidos in await asyncio.gather(*[res_privado_con_noLeidos(c["contacto_id"]) for c in contactos]):
        if r:
            r["no_leidos"] = no_leidos
            resultado[f"privado:{cid}"] = r

    # Grupos — paralelo
    grupos = await db.grupos.find({"miembros": usuario_id}).to_list(None)

    async def res_grupo(grupo_id: str):
        r = await _ultimo_mensaje_formateado(db, {"tipo": "grupo", "grupo_id": grupo_id})
        return grupo_id, r

    for gid, r in await asyncio.gather(*[res_grupo(str(g["_id"])) for g in grupos]):
        if r:
            resultado[f"grupo:{gid}"] = r

    return resultado


@router.get("/sala", summary="Historial sala general")
async def historial_sala(
    limite: int = Query(50, ge=1, le=200),
    antes_de: Optional[str] = Query(None, description="ISO timestamp: cargar mensajes anteriores a esta fecha"),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    db = get_db()
    filtro: dict = {"tipo": "sala"}
    if antes_de:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(antes_de.replace("Z", "+00:00"))
            filtro["created_at"] = {"$lt": dt}
        except ValueError:
            pass
    mensajes = await db.mensajes.find(filtro).sort("created_at", -1).limit(limite).to_list(None)
    mensajes.reverse()
    return await _enriquecer_mensajes(db, mensajes)


@router.get("/privado/{otro_usuario_id}", summary="Historial de chat privado")
async def historial_privado(
    otro_usuario_id: str,
    limite: int = Query(50, ge=1, le=200),
    antes_de: Optional[str] = Query(None, description="ISO timestamp: cargar mensajes anteriores a esta fecha"),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    db = get_db()
    usuario_id = usuario_actual["sub"]
    filtro: dict = {
        "tipo": "privado",
        "$or": [
            {"remitente_id": usuario_id, "destinatario_id": otro_usuario_id},
            {"remitente_id": otro_usuario_id, "destinatario_id": usuario_id}
        ]
    }
    if antes_de:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(antes_de.replace("Z", "+00:00"))
            filtro["created_at"] = {"$lt": dt}
        except ValueError:
            pass
    mensajes = await db.mensajes.find(filtro).sort("created_at", -1).limit(limite).to_list(None)
    mensajes.reverse()
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

    # Notificar al remitente que sus mensajes fueron leídos (via RabbitMQ → broadcast)
    if resultado.modified_count > 0:
        sala = manager.clave_privada(usuario_id, otro_usuario_id)
        await publicar_mensaje(sala, {
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
    """Elimina la conversación privada para ambos usuarios y borra archivos del disco."""
    db = get_db()
    usuario_id = usuario_actual["sub"]
    filtro = {
        "tipo": "privado",
        "$or": [
            {"remitente_id": usuario_id, "destinatario_id": otro_usuario_id},
            {"remitente_id": otro_usuario_id, "destinatario_id": usuario_id}
        ]
    }

    # Recopilar archivos a eliminar del disco
    msgs_con_archivos = await db.mensajes.find(
        {**filtro, "subtipo": {"$in": ["imagen", "audio", "video", "archivo"]}}
    ).to_list(None)

    resultado = await db.mensajes.delete_many(filtro)

    for msg in msgs_con_archivos:
        url = msg.get("contenido", "")
        if url.startswith("/uploads/chat/"):
            ruta = pathlib.Path(url.lstrip("/"))
            ruta.unlink(missing_ok=True)

    return {
        "mensaje": "Conversación eliminada para ambos usuarios",
        "mensajes_eliminados": resultado.deleted_count
    }


@router.post("/imagen", status_code=status.HTTP_201_CREATED, summary="Enviar imagen en el chat")
async def enviar_imagen(
    archivo: UploadFile = File(...),
    tipo_chat: str = Form(...),                    # sala | privado | grupo
    destinatario_id: Optional[str] = Form(None),
    grupo_id: Optional[str] = Form(None),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Recibe una imagen, la comprime con Pillow y la guarda. Publica el mensaje vía RabbitMQ."""
    db = get_db()
    usuario_id = usuario_actual["sub"]

    if tipo_chat not in ("sala", "privado", "grupo"):
        raise HTTPException(status_code=400, detail="tipo_chat inválido")
    if not archivo.content_type or not archivo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Solo se permiten imágenes")

    # Leer y comprimir con Pillow
    datos = await archivo.read()
    try:
        img = Image.open(io.BytesIO(datos)).convert("RGB")
        img.thumbnail((1200, 1200), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        datos_comprimidos = buf.getvalue()
    except Exception:
        raise HTTPException(status_code=400, detail="Imagen inválida o corrupta")

    # Guardar en disco
    nombre_archivo = f"{uuid.uuid4().hex}.jpg"
    ruta = UPLOADS_CHAT / nombre_archivo
    ruta.write_bytes(datos_comprimidos)
    url = f"/uploads/chat/{nombre_archivo}"

    # Obtener nombre del remitente
    from bson import ObjectId as ObjId
    usuario = await db.usuarios.find_one({"_id": ObjId(usuario_id)})
    nombre = usuario["nombre"] if usuario else "Desconocido"

    # Guardar en MongoDB
    doc = MensajeModel.nuevo(
        tipo=tipo_chat,
        remitente_id=usuario_id,
        contenido=url,
        destinatario_id=destinatario_id if tipo_chat == "privado" else None,
        grupo_id=grupo_id if tipo_chat == "grupo" else None,
        subtipo="imagen",
    )
    if tipo_chat == "privado":
        doc["leido"] = False
    resultado = await db.mensajes.insert_one(doc)
    msg_id = str(resultado.inserted_id)

    # Determinar sala para RabbitMQ
    if tipo_chat == "sala":
        sala = "sala_general"
    elif tipo_chat == "privado" and destinatario_id:
        sala = manager.clave_privada(usuario_id, destinatario_id)
    elif tipo_chat == "grupo" and grupo_id:
        sala = manager.clave_grupo(grupo_id)
    else:
        raise HTTPException(status_code=400, detail="Faltan parámetros para el tipo de chat")

    payload: dict = {
        "id": msg_id,
        "tipo": tipo_chat,
        "subtipo": "imagen",
        "remitente_id": usuario_id,
        "nombre_remitente": nombre,
        "contenido": url,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if tipo_chat == "privado" and destinatario_id:
        payload["destinatario_id"] = destinatario_id
        payload["leido"] = False
    if tipo_chat == "grupo" and grupo_id:
        payload["grupo_id"] = grupo_id

    await publicar_mensaje(sala, payload)
    logger.info("imagen enviada usuario=%s sala=%s archivo=%s", usuario_id[:8], sala, nombre_archivo)
    return payload


# MIME → (subtipo, extensión)
_MIME_MAP: dict[str, tuple[str, str]] = {
    "audio/webm": ("audio", "webm"),
    "audio/ogg": ("audio", "ogg"),
    "audio/wav": ("audio", "wav"),
    "audio/mp4": ("audio", "m4a"),
    "audio/mpeg": ("audio", "mp3"),
    "audio/aac": ("audio", "aac"),
    "video/mp4": ("video", "mp4"),
    "video/webm": ("video", "webm"),
    "video/ogg": ("video", "ogv"),
    "video/quicktime": ("video", "mov"),
    "application/pdf": ("archivo", "pdf"),
    "application/msword": ("archivo", "doc"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("archivo", "docx"),
    "application/vnd.ms-excel": ("archivo", "xls"),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ("archivo", "xlsx"),
    "application/vnd.ms-powerpoint": ("archivo", "ppt"),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ("archivo", "pptx"),
    "text/plain": ("archivo", "txt"),
    "application/zip": ("archivo", "zip"),
    "application/x-zip-compressed": ("archivo", "zip"),
}


@router.post("/archivo", status_code=status.HTTP_201_CREATED, summary="Enviar audio, video o archivo en el chat")
async def enviar_archivo(
    archivo: UploadFile = File(...),
    tipo_chat: str = Form(...),
    destinatario_id: Optional[str] = Form(None),
    grupo_id: Optional[str] = Form(None),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Recibe audio, video o documentos, guarda en disco y publica vía RabbitMQ."""
    db = get_db()
    usuario_id = usuario_actual["sub"]

    if tipo_chat not in ("sala", "privado", "grupo"):
        raise HTTPException(status_code=400, detail="tipo_chat inválido")

    content_type = (archivo.content_type or "").split(";")[0].strip().lower()

    # Determinar subtipo y extensión
    subtipo, ext = _MIME_MAP.get(content_type, (None, None))
    if subtipo is None:
        if content_type.startswith("audio/"):
            subtipo = "audio"
        elif content_type.startswith("video/"):
            subtipo = "video"
    if subtipo is None:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido")

    if ext is None:
        if archivo.filename and "." in archivo.filename:
            ext = archivo.filename.rsplit(".", 1)[-1].lower()
        else:
            ext = "bin"

    datos = await archivo.read()
    nombre_orig = archivo.filename or f"archivo.{ext}"
    nombre_guardado = f"{uuid.uuid4().hex}.{ext}"
    ruta = UPLOADS_CHAT / nombre_guardado
    ruta.write_bytes(datos)
    url = f"/uploads/chat/{nombre_guardado}"

    from bson import ObjectId as ObjId
    usuario = await db.usuarios.find_one({"_id": ObjId(usuario_id)})
    nombre = usuario["nombre"] if usuario else "Desconocido"

    doc = MensajeModel.nuevo(
        tipo=tipo_chat,
        remitente_id=usuario_id,
        contenido=url,
        destinatario_id=destinatario_id if tipo_chat == "privado" else None,
        grupo_id=grupo_id if tipo_chat == "grupo" else None,
        subtipo=subtipo,
        nombre_archivo=nombre_orig if subtipo == "archivo" else None,
    )
    if tipo_chat == "privado":
        doc["leido"] = False
    resultado = await db.mensajes.insert_one(doc)
    msg_id = str(resultado.inserted_id)

    if tipo_chat == "sala":
        sala = "sala_general"
    elif tipo_chat == "privado" and destinatario_id:
        sala = manager.clave_privada(usuario_id, destinatario_id)
    elif tipo_chat == "grupo" and grupo_id:
        sala = manager.clave_grupo(grupo_id)
    else:
        raise HTTPException(status_code=400, detail="Faltan parámetros para el tipo de chat")

    payload: dict = {
        "id": msg_id,
        "tipo": tipo_chat,
        "subtipo": subtipo,
        "remitente_id": usuario_id,
        "nombre_remitente": nombre,
        "contenido": url,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if subtipo == "archivo":
        payload["nombre_archivo"] = nombre_orig
    if tipo_chat == "privado" and destinatario_id:
        payload["destinatario_id"] = destinatario_id
        payload["leido"] = False
    if tipo_chat == "grupo" and grupo_id:
        payload["grupo_id"] = grupo_id

    await publicar_mensaje(sala, payload)
    logger.info("archivo enviado usuario=%s sala=%s tipo=%s archivo=%s", usuario_id[:8], sala, subtipo, nombre_guardado)
    return payload


@router.get("/grupo/{grupo_id}", summary="Historial de mensajes de grupo")
async def historial_grupo(
    grupo_id: str,
    limite: int = Query(50, ge=1, le=200),
    antes_de: Optional[str] = Query(None, description="ISO timestamp: cargar mensajes anteriores a esta fecha"),
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

    filtro: dict = {"tipo": "grupo", "grupo_id": grupo_id}
    if antes_de:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(antes_de.replace("Z", "+00:00"))
            filtro["created_at"] = {"$lt": dt}
        except ValueError:
            pass

    mensajes = await db.mensajes.find(filtro).sort("created_at", -1).limit(limite).to_list(None)
    mensajes.reverse()
    return await _enriquecer_mensajes(db, mensajes)


def _sala_de_mensaje(msg: dict) -> str:
    """Devuelve la clave de sala para publicar por RabbitMQ dado un documento de mensaje."""
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


@router.patch("/{msg_id}", status_code=200, summary="Editar contenido de un mensaje propio")
async def editar_mensaje(
    msg_id: str,
    datos: EditarMensajeSchema,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """Permite al remitente editar el texto de su propio mensaje. Solo mensajes de tipo texto."""
    db = get_db()
    usuario_id = usuario_actual["sub"]

    try:
        msg = await db.mensajes.find_one({"_id": ObjectId(msg_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="ID de mensaje inválido")

    if not msg:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
    if msg.get("remitente_id") != usuario_id:
        raise HTTPException(status_code=403, detail="No puedes editar mensajes de otros usuarios")
    if msg.get("eliminado"):
        raise HTTPException(status_code=400, detail="No se puede editar un mensaje eliminado")
    if msg.get("subtipo") in ("imagen", "audio", "video", "archivo", "encuesta"):
        raise HTTPException(status_code=400, detail="Solo se pueden editar mensajes de texto")

    nuevo_contenido = datos.contenido.strip()
    await db.mensajes.update_one(
        {"_id": ObjectId(msg_id)},
        {"$set": {"contenido": nuevo_contenido, "editado": True}},
    )

    sala = _sala_de_mensaje(msg)
    await publicar_mensaje(sala, {
        "tipo": "mensaje_editado",
        "id": msg_id,
        "contenido": nuevo_contenido,
    })
    return {"id": msg_id, "contenido": nuevo_contenido, "editado": True}


@router.delete("/{msg_id}/propio", status_code=200, summary="Eliminar (soft delete) un mensaje propio")
async def eliminar_mensaje_propio(
    msg_id: str,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """Soft-delete: marca el mensaje como eliminado y borra el archivo del disco si aplica."""
    db = get_db()
    usuario_id = usuario_actual["sub"]

    try:
        msg = await db.mensajes.find_one({"_id": ObjectId(msg_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="ID de mensaje inválido")

    if not msg:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
    if msg.get("remitente_id") != usuario_id:
        raise HTTPException(status_code=403, detail="No puedes eliminar mensajes de otros usuarios")
    if msg.get("eliminado"):
        raise HTTPException(status_code=400, detail="El mensaje ya fue eliminado")

    # Borrar archivo del disco si es un adjunto
    if msg.get("subtipo") in ("imagen", "audio", "video", "archivo"):
        url = msg.get("contenido", "")
        if url.startswith("/uploads/chat/"):
            ruta = pathlib.Path(url.lstrip("/"))
            ruta.unlink(missing_ok=True)

    await db.mensajes.update_one(
        {"_id": ObjectId(msg_id)},
        {"$set": {"eliminado": True, "contenido": ""}},
    )

    sala = _sala_de_mensaje(msg)
    await publicar_mensaje(sala, {
        "tipo": "mensaje_eliminado",
        "id": msg_id,
    })
    return {"id": msg_id, "eliminado": True}
