"""
Configuración central de logging para JHT Chat.

Cada request HTTP y cada mensaje WS obtiene un request_id único (UUID corto)
que viaja a través de Redis, RabbitMQ y el consumer, permitiendo trazar una
acción completa de punta a punta en los logs.

Uso:
    from app.logger import get_logger, request_id_ctx
    logger = get_logger(__name__)
    logger.info("algo pasó")  # incluye automáticamente el request_id del contexto
"""
import logging
import sys
from contextvars import ContextVar

# Variable de contexto async-safe: cada corrutina tiene su propio valor
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    """Inyecta el request_id del contexto en cada registro de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()  # type: ignore[attr-defined]
        return True


def setup_logging() -> None:
    """Configura el handler raíz una sola vez al arrancar la aplicación."""
    fmt = "%(asctime)s [%(request_id)s] %(levelname)-5s %(name)s: %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)

    # Silenciar loggers ruidosos de librerías externas
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("aio_pika").setLevel(logging.WARNING)
    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
