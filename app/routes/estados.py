"""
Endpoints de estados (stories): subir, listar y eliminar.
Los estados expiran automáticamente después de DURACION_MINUTOS minutos.
"""
import io
import uuid
import pathlib
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File
from PIL import Image
from bson import ObjectId
from app.middleware.auth_middleware import obtener_usuario_actual
from app.models.estado import EstadoModel
from app.database import get_db

router = APIRouter(prefix="/estados", tags=["Estados"])

UPLOADS_ESTADOS = pathlib.Path("uploads/estados")


@router.post("", status_code=status.HTTP_201_CREATED, summary="Subir un estado")
async def subir_estado(
    archivo: UploadFile = File(...),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Sube una imagen como estado. Expira en DURACION_MINUTOS minutos."""
    if not archivo.content_type or not archivo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Solo se permiten imágenes")

    datos = await archivo.read()
    try:
        img = Image.open(io.BytesIO(datos)).convert("RGB")
        img.thumbnail((1080, 1920), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80, optimize=True)
        datos_comprimidos = buf.getvalue()
    except Exception:
        raise HTTPException(status_code=400, detail="Imagen inválida o corrupta")

    nombre_archivo = f"{uuid.uuid4().hex}.jpg"
    ruta = UPLOADS_ESTADOS / nombre_archivo
    ruta.write_bytes(datos_comprimidos)
    url = f"/uploads/estados/{nombre_archivo}"

    db = get_db()
    usuario_id = usuario_actual["sub"]
    usuario = await db.usuarios.find_one({"_id": ObjectId(usuario_id)})
    nombre_usuario = usuario["nombre"] if usuario else "Desconocido"

    doc = EstadoModel.nuevo(usuario_id, nombre_usuario, url)
    resultado = await db.estados.insert_one(doc)

    return {
        "id": str(resultado.inserted_id),
        "usuario_id": usuario_id,
        "nombre_usuario": nombre_usuario,
        "url_imagen": url,
        "created_at": doc["created_at"].isoformat(),
        "expira_at": doc["expira_at"].isoformat(),
    }


def _dt(dt) -> str:
    """Serializa datetime a ISO 8601 con sufijo Z para que JS lo interprete como UTC."""
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


@router.get("", summary="Listar estados activos de mis contactos")
async def listar_estados(
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Retorna los estados no expirados del usuario y sus contactos."""
    db = get_db()
    usuario_id = usuario_actual["sub"]
    ahora = datetime.now(timezone.utc)

    # IDs de mis contactos
    mis_contactos = await db.contactos.find(
        {"usuario_id": usuario_id}
    ).to_list(length=None)
    contacto_ids = [c["contacto_id"] for c in mis_contactos]

    estados = await db.estados.find({
        "expira_at": {"$gt": ahora},
        "usuario_id": {"$in": [usuario_id] + contacto_ids}
    }).sort("created_at", -1).to_list(length=None)

    return [
        {
            "id": str(e["_id"]),
            "usuario_id": e["usuario_id"],
            "nombre_usuario": e["nombre_usuario"],
            "url_imagen": e["url_imagen"],
            "created_at": _dt(e["created_at"]),
            "expira_at": _dt(e["expira_at"]),
        }
        for e in estados
    ]


@router.delete("/{estado_id}", status_code=status.HTTP_200_OK, summary="Eliminar propio estado")
async def eliminar_estado(
    estado_id: str,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Elimina un estado propio y su imagen del servidor."""
    db = get_db()
    usuario_id = usuario_actual["sub"]

    try:
        estado = await db.estados.find_one({"_id": ObjectId(estado_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="ID inválido")

    if not estado:
        raise HTTPException(status_code=404, detail="Estado no encontrado")
    if estado["usuario_id"] != usuario_id:
        raise HTTPException(status_code=403, detail="No puedes eliminar este estado")

    ruta = pathlib.Path(estado["url_imagen"].lstrip("/"))
    ruta.unlink(missing_ok=True)
    await db.estados.delete_one({"_id": ObjectId(estado_id)})

    return {"mensaje": "Estado eliminado"}
