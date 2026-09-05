from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PrecioProveedor(BaseModel):
    proveedor: str
    sku_proveedor: str
    descripcion: Optional[str] = None
    precio_usd: float
    moneda_original: str = "USD"
    disponibilidad: bool = True
    url_producto: Optional[str] = None
    fecha: datetime


class RespuestaScraping(BaseModel):
    status: str
    ejecutado_en: datetime
    total_items: int
    actualizados: int
    errores: list[dict]
    items: list[PrecioProveedor]