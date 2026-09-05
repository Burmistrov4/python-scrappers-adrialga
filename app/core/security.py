import os

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key(
    api_key: str = Security(api_key_header),
) -> str:
    """
    Dependencia de seguridad inter-servicio.

    Valida la cabecera X-API-Key contra la variable de entorno SCRAPING_API_KEY.
    Retorna 401 si la clave no está presente o no coincide.
    """
    clave_esperada = os.getenv("SCRAPING_API_KEY", "")

    if not clave_esperada:
        # Sin clave configurada en el entorno, se rechaza todo acceso
        # para no exponer el microservicio accidentalmente.
        raise HTTPException(
            status_code=401,
            detail="Servicio sin SCRAPING_API_KEY configurada en el servidor",
        )

    if not api_key or api_key != clave_esperada:
        raise HTTPException(status_code=401, detail="API Key inválida o ausente")

    return api_key