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

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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