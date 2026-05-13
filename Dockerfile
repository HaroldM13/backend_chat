FROM python:3.12-slim

WORKDIR /app

# Copiar requirements primero para aprovechar el cache de capas de Docker.
# Si el código cambia pero requirements.txt no, esta capa se reutiliza
# y el rebuild es instantáneo.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
