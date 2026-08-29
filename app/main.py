from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import bcv, seniat

app = FastAPI(
    title="Servicios Auxiliares POS",
    version="1.0.0"
)

# Permitir conexiones desde el Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(seniat.router)
app.include_router(bcv.router)


@app.get("/")
def read_root():
    return {"status": "ok", "message": "API de Servicios Auxiliares en ejecución"}