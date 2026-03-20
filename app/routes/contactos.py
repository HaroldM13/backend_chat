"""
Endpoints de gestión de contactos.
Al eliminar un contacto, también se eliminan todos los mensajes privados con esa persona.
"""
from fastapi import APIRouter, HTTPException, status, Request, Depends
from bson import ObjectId
from app.schemas.contacto import AgregarContactoSchema
from app.models.contacto import ContactoModel
from app.middleware.auth_middleware import obtener_usuario_actual
from app.services.log_service import registrar_log
from app.database import get_db

router = APIRouter(prefix="/contactos", tags=["Contactos"])


@router.post("", status_code=status.HTTP_201_CREATED,
             summary="Agregar contacto por teléfono")
async def agregar_contacto(
    datos: AgregarContactoSchema,
    request: Request,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    db = get_db()
    ip = request.client.host if request.client else "desconocida"
    usuario_id = usuario_actual["sub"]

    contacto_usuario = await db.usuarios.find_one({"telefono": datos.telefono})
    if not contacto_usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado con ese teléfono")

    contacto_id = str(contacto_usuario["_id"])

    if contacto_id == usuario_id:
        raise HTTPException(status_code=400, detail="No puedes agregarte a ti mismo como contacto")

    ya_existe = await db.contactos.find_one({"usuario_id": usuario_id, "contacto_id": contacto_id})
    if ya_existe:
        raise HTTPException(status_code=409, detail="Este usuario ya está en tus contactos")

    await db.contactos.insert_one(ContactoModel.nuevo(usuario_id, contacto_id))

    await registrar_log("CONTACT_ADDED", "success", ip, usuario_id,
                        {"contacto_id": contacto_id, "telefono": datos.telefono})

    return {
        "mensaje": "Contacto agregado exitosamente",
        "contacto": {
            "id": contacto_id,
            "nombre": contacto_usuario["nombre"],
            "telefono": contacto_usuario["telefono"]
        }
    }


@router.get("", summary="Listar contactos")
async def listar_contactos(usuario_actual: dict = Depends(obtener_usuario_actual)):
    db = get_db()
    usuario_id = usuario_actual["sub"]
    contactos_docs = await db.contactos.find({"usuario_id": usuario_id}).to_list(length=None)

    resultado = []
    for c in contactos_docs:
        u = await db.usuarios.find_one({"_id": ObjectId(c["contacto_id"])})
        if u:
            resultado.append({
                "contacto_id": c["contacto_id"],
                "nombre": u["nombre"],
                "telefono": u["telefono"],
                "created_at": c["created_at"]
            })
    return resultado


@router.delete(
    "/{contacto_id}",
    status_code=status.HTTP_200_OK,
    summary="Eliminar contacto",
    description=(
        "Elimina el contacto de la lista Y borra todos los mensajes privados "
        "intercambiados con esa persona (en ambas direcciones)."
    )
)
async def eliminar_contacto(
    contacto_id: str,
    request: Request,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    db = get_db()
    ip = request.client.host if request.client else "desconocida"
    usuario_id = usuario_actual["sub"]

    resultado = await db.contactos.delete_one({
        "usuario_id": usuario_id,
        "contacto_id": contacto_id
    })

    if resultado.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    # Eliminar todos los mensajes privados entre ambos (en ambas direcciones)
    eliminados = await db.mensajes.delete_many({
        "tipo": "privado",
        "$or": [
            {"remitente_id": usuario_id, "destinatario_id": contacto_id},
            {"remitente_id": contacto_id, "destinatario_id": usuario_id}
        ]
    })

    await registrar_log("CONTACT_DELETED", "success", ip, usuario_id,
                        {"contacto_id": contacto_id,
                         "mensajes_eliminados": eliminados.deleted_count})

    return {
        "mensaje": "Contacto eliminado y mensajes privados borrados",
        "mensajes_eliminados": eliminados.deleted_count
    }
