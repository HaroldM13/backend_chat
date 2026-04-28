"""
Endpoints HTTP para historial, marcar como leído, eliminar conversación e imágenes.
"""
import io
import uuid
import pathlib
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends, Query, Request, UploadFile, File, Form
from PIL import Image
from bson import ObjectId
from app.middleware.auth_middleware import obtener_usuario_actual
from app.websocket.manager import manager
from app.services.rabbit_service import publicar_mensaje
from app.models.mensaje import MensajeModel
from app.database import get_db

UPLOADS_CHAT = pathlib.Path("uploads/chat")

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
            "subtipo": msg.get("subtipo"),   # None para texto, "imagen" para imágenes
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
    return payload


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
