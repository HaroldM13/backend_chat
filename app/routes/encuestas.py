"""
Endpoints para encuestas (polls) en el chat.
Colección mensajes con subtipo='encuesta', contenido=JSON.
Colección votos_encuesta: { mensaje_id, usuario_id, opcion_id }
"""
import json
import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from bson import ObjectId
from app.middleware.auth_middleware import obtener_usuario_actual
from app.database import get_db
from app.services.rabbit_service import publicar_mensaje
from app.websocket.manager import manager
from app.models.mensaje import MensajeModel

router = APIRouter(prefix="/encuestas", tags=["Encuestas"])


class CrearEncuestaSchema(BaseModel):
    pregunta: str = Field(..., min_length=1, max_length=200)
    opciones: List[str] = Field(..., min_length=2, max_length=4)
    tipo_chat: str
    destinatario_id: Optional[str] = None
    grupo_id: Optional[str] = None


class VotarSchema(BaseModel):
    opcion_id: str


def _sala_de_encuesta(tipo_chat: str, remitente_id: str, destinatario_id: Optional[str], grupo_id: Optional[str]) -> str:
    """Calcula la clave de sala para publicar vía RabbitMQ."""
    if tipo_chat == "sala":
        return "sala_general"
    if tipo_chat == "privado" and destinatario_id:
        return manager.clave_privada(remitente_id, destinatario_id)
    if tipo_chat == "grupo" and grupo_id:
        return manager.clave_grupo(grupo_id)
    raise ValueError("Faltan parámetros para determinar la sala")


@router.post("", status_code=201)
async def crear_encuesta(
    payload: CrearEncuestaSchema,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """Crea una encuesta y la publica como mensaje especial con subtipo='encuesta'."""
    db = get_db()
    usuario_id = usuario_actual["sub"]

    if payload.tipo_chat not in ("sala", "privado", "grupo"):
        raise HTTPException(status_code=400, detail="tipo_chat inválido")

    opciones_limpias = [o.strip() for o in payload.opciones if o.strip()]
    if len(opciones_limpias) < 2:
        raise HTTPException(status_code=400, detail="Se necesitan al menos 2 opciones no vacías")

    opciones = [
        {"id": _uuid_mod.uuid4().hex[:8], "texto": texto}
        for texto in opciones_limpias
    ]
    contenido = json.dumps(
        {"pregunta": payload.pregunta.strip(), "opciones": opciones},
        ensure_ascii=False,
    )

    doc = MensajeModel.nuevo(
        tipo=payload.tipo_chat,
        remitente_id=usuario_id,
        contenido=contenido,
        destinatario_id=payload.destinatario_id if payload.tipo_chat == "privado" else None,
        grupo_id=payload.grupo_id if payload.tipo_chat == "grupo" else None,
        subtipo="encuesta",
    )
    resultado = await db.mensajes.insert_one(doc)
    msg_id = str(resultado.inserted_id)

    usuario = await db.usuarios.find_one({"_id": ObjectId(usuario_id)})
    nombre = usuario["nombre"] if usuario else "Desconocido"

    try:
        sala = _sala_de_encuesta(payload.tipo_chat, usuario_id, payload.destinatario_id, payload.grupo_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ws_payload: dict = {
        "id": msg_id,
        "tipo": payload.tipo_chat,
        "subtipo": "encuesta",
        "remitente_id": usuario_id,
        "nombre_remitente": nombre,
        "contenido": contenido,
        "opciones": opciones,
        "votos": {},
        "mi_voto": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload.tipo_chat == "privado" and payload.destinatario_id:
        ws_payload["destinatario_id"] = payload.destinatario_id
    if payload.tipo_chat == "grupo" and payload.grupo_id:
        ws_payload["grupo_id"] = payload.grupo_id

    await publicar_mensaje(sala, ws_payload)
    return ws_payload


@router.post("/{msg_id}/votar", status_code=200)
async def votar_encuesta(
    msg_id: str,
    payload: VotarSchema,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    """Registra o actualiza el voto del usuario en una encuesta y difunde los resultados."""
    db = get_db()
    usuario_id = usuario_actual["sub"]

    try:
        msg = await db.mensajes.find_one({"_id": ObjectId(msg_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="ID de mensaje inválido")

    if not msg or msg.get("subtipo") != "encuesta":
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")

    # Validar que la opción existe en la encuesta
    try:
        datos = json.loads(msg["contenido"])
        ids_validos = {o["id"] for o in datos.get("opciones", [])}
    except Exception:
        ids_validos = set()

    if payload.opcion_id not in ids_validos:
        raise HTTPException(status_code=400, detail="Opción inválida")

    # upsert: un voto por usuario
    await db.votos_encuesta.update_one(
        {"mensaje_id": msg_id, "usuario_id": usuario_id},
        {"$set": {"opcion_id": payload.opcion_id}},
        upsert=True,
    )

    votos_lista = await db.votos_encuesta.find({"mensaje_id": msg_id}).to_list(None)
    votos: dict = {}
    mi_voto: Optional[str] = None
    for v in votos_lista:
        oid = v["opcion_id"]
        votos[oid] = votos.get(oid, 0) + 1
        if v["usuario_id"] == usuario_id:
            mi_voto = oid

    # Determinar sala
    tipo = msg.get("tipo", "sala")
    if tipo == "sala":
        sala = "sala_general"
    elif tipo == "privado":
        sala = manager.clave_privada(msg.get("remitente_id", ""), msg.get("destinatario_id", ""))
    else:
        sala = manager.clave_grupo(msg.get("grupo_id", ""))

    await publicar_mensaje(sala, {
        "tipo": "voto_encuesta",
        "mensaje_id": msg_id,
        "votos": votos,
        "usuario_id": usuario_id,
        "opcion_id": payload.opcion_id,
    })
    return {"votos": votos, "mi_voto": mi_voto}
