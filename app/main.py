import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import bcv, proveedores, seniat

app = FastAPI(
    title="Servicios Auxiliares POS",
    version="1.1.0"
)

# Orígenes permitidos desde variable de entorno (separados por coma),
# con fallback a entornos locales de desarrollo.
_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]

# En desarrollo se permite CUALQUIER origen por IP (localhost, LAN 192.168/10/
# 172.16-31 o la IP pública de la máquina) para probar desde el móvil/PC sin
# reconfigurar la lista. En producción (APP_ENV=production) solo la lista blanca.
_es_desarrollo = os.getenv("APP_ENV", "development") != "production"
_allow_origin_regex = (
    r"^https?://(\d{1,3}(\.\d{1,3}){3}|localhost|127\.0\.0\.1)(:\d+)?$"
    if _es_desarrollo
    else None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(seniat.router)
app.include_router(bcv.router)
app.include_router(proveedores.router)


@app.get("/")
def read_root():
    return {"status": "ok", "message": "API de Servicios Auxiliares en ejecución"}