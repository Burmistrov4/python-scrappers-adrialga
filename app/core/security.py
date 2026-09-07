import os

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key(
    api_key: str = Security(api_key_header),
) -> str:
    """
    Dependencia de seguridad inter-servicio.

    Modo de operación (decisión de despliegue del negocio):
    - Si SCRAPING_API_KEY NO está configurada en el entorno → acceso libre.
      El microservicio se considera interno (red privada Railway / localhost)
      y no expone endpoints públicos. El backend Node no envía la cabecera.
    - Si SCRAPING_API_KEY está configurada → se valida la cabecera X-API-Key
      (401 si falta o no coincide), igual que antes.
    """
    clave_esperada = os.getenv("SCRAPING_API_KEY", "")

    # Modo interno: sin clave configurada, no se exige cabecera.
    if not clave_esperada:
        return ""

    if not api_key or api_key != clave_esperada:
        raise HTTPException(status_code=401, detail="API Key inválida o ausente")

    return api_key