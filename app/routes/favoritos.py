"""
Endpoints para gestión de chats favoritos por usuario.
"""
from datetime import datetime, timezone
from urllib.parse import unquote
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.middleware.auth_middleware import obtener_usuario_actual
from app.database import get_db

router = APIRouter(prefix="/favoritos", tags=["Favoritos"])


class FavoritoPayload(BaseModel):
    chat_key: str


@router.get("", summary="Listar favoritos del usuario")
async def listar_favoritos(usuario_actual: dict = Depends(obtener_usuario_actual)):
    db = get_db()
    favs = await db.favoritos.find({"usuario_id": usuario_actual["sub"]}).to_list(None)
    return [{"chat_key": f["chat_key"], "created_at": f["created_at"]} for f in favs]


@router.post("", status_code=201, summary="Agregar chat a favoritos")
async def agregar_favorito(
    payload: FavoritoPayload,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    db = get_db()
    await db.favoritos.update_one(
        {"usuario_id": usuario_actual["sub"], "chat_key": payload.chat_key},
        {"$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {"chat_key": payload.chat_key}


@router.delete("/{chat_key_enc}", status_code=200, summary="Quitar chat de favoritos")
async def quitar_favorito(
    chat_key_enc: str,
    usuario_actual: dict = Depends(obtener_usuario_actual),
):
    db = get_db()
    chat_key = unquote(chat_key_enc)
    await db.favoritos.delete_one({"usuario_id": usuario_actual["sub"], "chat_key": chat_key})
    return {"ok": True}
