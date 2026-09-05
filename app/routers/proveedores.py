import random
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import get_api_key
from app.schemas.proveedores import PrecioProveedor, RespuestaScraping

router = APIRouter(
    prefix="/api/v1/scrapers/proveedores",
    tags=["Proveedores"],
    dependencies=[Depends(get_api_key)],
)


class SolicitudEjecutar(BaseModel):
    """Cuerpo opcional del POST /ejecutar.

    Lista de objetivos (SKUs de proveedor o URLs de producto) a consultar.
    Si se omite o queda vacía, el scraper consulta el catálogo completo.
    """

    objetivos: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Stub funcional: en fases posteriores esto se reemplaza por scrapers reales
# por proveedor (Playwright/BS4) usando `objetivos` como filtro.
# ---------------------------------------------------------------------------
CATALOGO_DEMO = [
    {
        "proveedor": "ProveedorDemo",
        "sku_proveedor": "PIN-0001",
        "descripcion": "Pintura base agua 4L",
        "precio_usd": 12.5,
        "moneda_original": "USD",
        "disponibilidad": True,
        "url_producto": "https://proveedor-demo.com/p/pin-0001",
    },
    {
        "proveedor": "ProveedorDemo",
        "sku_proveedor": "FER-0042",
        "descripcion": "Martillo 16oz mango fibra",
        "precio_usd": 8.75,
        "moneda_original": "USD",
        "disponibilidad": True,
        "url_producto": "https://proveedor-demo.com/p/fer-0042",
    },
    {
        "proveedor": "ProveedorDemo",
        "sku_proveedor": "HEZ-0099",
        "descripcion": "Kit destornilladores 12 pzs",
        "precio_usd": None,  # simula fallo de parsing en el scraper
        "moneda_original": "USD",
        "disponibilidad": False,
        "url_producto": "https://proveedor-demo.com/p/hez-0099",
    },
]


@router.post("/ejecutar", response_model=RespuestaScraping)
async def ejecutar_scraper_proveedores(
    solicitud: SolicitudEjecutar | None = None,
) -> RespuestaScraping:
    """
    Ejecuta el scraping de precios de proveedores.

    Recibe una lista opcional de SKUs/URLs a consultar. Si no se envía,
    se consulta el catálogo completo. Retorna una RespuestaScraping.
    """
    ejecutado_en = datetime.now(timezone.utc)
    objetivos = solicitud.objetivos if solicitud else None
    items: list[PrecioProveedor] = []
    errores: list[dict] = []

    for producto in CATALOGO_DEMO:
        sku = producto["sku_proveedor"]
        if objetivos and sku not in objetivos:
            continue

        if producto["precio_usd"] is None:
            errores.append(
                {
                    "sku_proveedor": sku,
                    "motivo": "No se pudo extraer el precio de la página del proveedor",
                }
            )
            continue

        items.append(
            PrecioProveedor(
                **{**producto, "precio_usd": round(producto["precio_usd"], 2)},
                fecha=ejecutado_en,
            )
        )

    return RespuestaScraping(
        status="completado",
        ejecutado_en=ejecutado_en,
        total_items=len(items) + len(errores),
        actualizados=len(items),
        errores=errores,
        items=items,
    )


# Variabilidad simulada opcional para pruebas de integración (precio fluctuante)
def _precio_con_variacion(precio: float) -> float:
    return round(precio * random.uniform(0.98, 1.02), 2)