"""
Servicio Twilio Verify: envío y verificación de códigos OTP por SMS.

Flujo:
  1. enviar_otp(telefono) → Twilio envía SMS con código de 6 dígitos
  2. verificar_otp(telefono, codigo) → Twilio valida el código
     retorna True si es correcto, False si no

Las llamadas al SDK de Twilio son síncronas, se ejecutan en un
thread pool con asyncio.to_thread() para no bloquear el event loop.
"""
import os
import asyncio
from twilio.rest import Client

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
VERIFY_SID = os.getenv("TWILIO_VERIFY_SID", "")


def _formatear_telefono(telefono: str) -> str:
    """Agrega +57 si el número no tiene código de país."""
    t = telefono.strip().replace(" ", "").replace("-", "")
    if not t.startswith("+"):
        t = f"+57{t}"
    return t


async def enviar_otp(telefono: str) -> None:
    """Envía un código OTP al número via Twilio Verify."""
    numero = _formatear_telefono(telefono)

    def _enviar() -> None:
        cliente = Client(ACCOUNT_SID, AUTH_TOKEN)
        cliente.verify.v2.services(VERIFY_SID).verifications.create(
            to=numero,
            channel="sms"
        )

    await asyncio.to_thread(_enviar)


async def verificar_otp(telefono: str, codigo: str) -> bool:
    """
    Verifica el código OTP ingresado por el usuario.
    Retorna True si el código es correcto y está aprobado.
    """
    numero = _formatear_telefono(telefono)

    def _verificar() -> bool:
        try:
            cliente = Client(ACCOUNT_SID, AUTH_TOKEN)
            resultado = cliente.verify.v2.services(VERIFY_SID).verification_checks.create(
                to=numero,
                code=codigo
            )
            return resultado.status == "approved"
        except Exception:
            return False

    return await asyncio.to_thread(_verificar)
