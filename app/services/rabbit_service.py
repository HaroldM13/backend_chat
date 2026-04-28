"""
Servicio RabbitMQ: cola de mensajes de chat.

Flujo de un mensaje:
  WS recibe texto → guarda en MongoDB → publicar_mensaje() → RabbitMQ
  → consumer (on_mensaje) → manager.broadcast() → clientes WebSocket

El exchange es FANOUT con una cola exclusiva/anónima por instancia.
Esto desacopla la recepción del mensaje de su distribución a los clientes,
y sienta las bases para escalar a múltiples instancias en el futuro.
"""
import os
import json
from typing import Optional
import aio_pika
from aio_pika.abc import AbstractRobustConnection, AbstractChannel

_conexion: Optional[AbstractRobustConnection] = None
_canal: Optional[AbstractChannel] = None

EXCHANGE = "chat_mensajes"


async def conectar_rabbit() -> None:
    global _conexion, _canal
    url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
    _conexion = await aio_pika.connect_robust(url)
    _canal = await _conexion.channel()
    await _canal.declare_exchange(EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True)


async def cerrar_rabbit() -> None:
    global _conexion, _canal
    if _canal:
        await _canal.close()
    if _conexion:
        await _conexion.close()


async def publicar_mensaje(sala: str, mensaje: dict) -> None:
    """Publica un mensaje en el exchange FANOUT de RabbitMQ."""
    if _canal is None:
        return
    try:
        exchange = await _canal.get_exchange(EXCHANGE)
        body = json.dumps({"sala": sala, "mensaje": mensaje}).encode()
        await exchange.publish(
            aio_pika.Message(body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key=""
        )
    except Exception:
        pass


async def iniciar_consumer() -> None:
    """
    Lanza el consumer que escucha el exchange y hace broadcast via manager.

    Usa un canal propio (independiente del canal de publicación) y una cola
    exclusiva anónima que se destruye cuando la conexión se cierra.
    """
    from app.websocket.manager import manager

    if _conexion is None:
        return

    canal_consumer = await _conexion.channel()
    await canal_consumer.set_qos(prefetch_count=10)

    exchange = await canal_consumer.declare_exchange(
        EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True
    )
    # Cola exclusiva: temporal, se elimina al desconectar
    cola = await canal_consumer.declare_queue("", exclusive=True)
    await cola.bind(exchange)

    async def on_mensaje(message: aio_pika.IncomingMessage) -> None:
        async with message.process():
            try:
                data = json.loads(message.body.decode())
                await manager.broadcast(data["sala"], data["mensaje"])
            except Exception:
                pass

    await cola.consume(on_mensaje)
