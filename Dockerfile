# Microservicio de scrapers (FastAPI) — BCV, SENIAT y proveedores.
#
# Es OPCIONAL desde el 2026-10-14: el backend Node lee bcv.org.ve directamente
# (nivel 1b de la cascada de tasa), así que la tasa funciona sin este servicio.
# Se levanta solo si se quiere el camino completo:
#   docker compose --profile scraper up -d
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# APP_ENV=production desactiva el comodín de CORS por IP; hay que declarar los
# orígenes permitidos en ALLOWED_ORIGINS.
ENV APP_ENV=production

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
