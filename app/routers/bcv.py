import re
from fastapi import APIRouter, HTTPException
import httpx
from bs4 import BeautifulSoup

router = APIRouter(prefix="/api/v1/bcv", tags=["BCV"])


@router.get("/tasa")
async def obtener_tasa_bcv():
    url = "https://www.bcv.org.ve/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"
    }

    # TLS verificado de forma normal (verify=True es el valor por defecto).
    # El sitio del BCV ha presentado históricamente una cadena de certificados
    # rota/incompleta. NO desactivamos la verificación como solución: si la
    # verificación falla, devolvemos 503 documentado y el backend aplica su
    # fallback (última tasa persistida), nunca una tasa inventada como oficial.
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code != 200:
                raise HTTPException(
                    status_code=502, detail="No se pudo obtener la página del BCV"
                )

            soup = BeautifulSoup(res.text, "html.parser")
            dolar_div = soup.find("div", {"id": "dolar"})

            if not dolar_div:
                raise HTTPException(
                    status_code=500,
                    detail="No se encontró el contenedor de la tasa en la web del BCV",
                )

            field_content = dolar_div.find("div", class_="field-content")
            if not field_content:
                field_content = dolar_div.find("strong")

            tasa_str = field_content.text.strip()
            # El BCV usa '.' como separador de miles y ',' como decimal
            # (ej. "1.234,56"). Normalizamos a formato float estándar.
            tasa_str = tasa_str.replace(".", "").replace(",", ".")
            tasa_val = float(re.sub(r"[^\d.]", "", tasa_str))

            return {
                "moneda": "USD",
                "tasa": tasa_val,
                "origen": "Banco Central de Venezuela",
            }

        except httpx.ConnectError as e:
            # Falla de conexión/TLS (incluye cadena de certificados del BCV rota).
            raise HTTPException(
                status_code=503,
                detail=(
                    "No se pudo establecer una conexión TLS verificada con el BCV "
                    f"({type(e).__name__}). La tasa oficial en vivo no está disponible; "
                    "el sistema debe usar la última tasa persistida como fallback."
                ),
            )
        except Exception as e:
            raise HTTPException(
                status_code=503, detail=f"Error al obtener tasa BCV: {str(e)}"
            )