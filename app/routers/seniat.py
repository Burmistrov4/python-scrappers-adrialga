import re
import xml.etree.ElementTree as ET
from fastapi import APIRouter, HTTPException
import httpx

router = APIRouter(prefix="/api/v1/seniat", tags=["SENIAT"])


def calcular_rif_completo(cedula_o_rif: str) -> str:
    """
    Formatea la entrada al estándar de 10 caracteres del SENIAT (Ej: J405837357 -> J405837357 / V28036972 -> V280369720).
    """
    val = re.sub(r"[^A-Z0-9]", "", cedula_o_rif.strip().upper())
    if not val:
        return ""

    if len(val) == 10 and val[0] in "VEJGP":
        return val

    tipo = val[0] if val[0] in "VEJGP" else "V"
    num_str = re.sub(r"\D", "", val)

    if val.isdigit() and len(val) == 9:
        tipo = "J" if val[0] in "3456" else "V"
        num_str = val

    if len(num_str) > 8:
        num_str = num_str[:8]
    else:
        num_str = num_str.zfill(8)

    bases = {"V": 4, "E": 8, "J": 12, "P": 16, "G": 20}
    factores = [3, 2, 7, 6, 5, 4, 3, 2]

    base = bases.get(tipo, 4)
    suma = base + sum(int(d) * f for d, f in zip(num_str, factores))
    resto = suma % 11
    digito = 11 - resto
    if digito >= 10:
        digito = 0

    return f"{tipo}{num_str}{digito}"


@router.get("/consultar/{cedula_o_rif}")
async def consultar_seniat(cedula_o_rif: str):
    rif = calcular_rif_completo(cedula_o_rif)

    if not rif:
        raise HTTPException(status_code=400, detail="Formato de Cédula/RIF inválido")

    url = f"http://contribuyente.seniat.gob.ve/getContribuyente/getrif?rif={rif}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
        "Host": "contribuyente.seniat.gob.ve",
    }

    try:
        async with httpx.AsyncClient(timeout=8.0, verify=False) as client:
            res = await client.get(url, headers=headers)

            if res.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"El servidor del SENIAT respondió con código HTTP {res.status_code}",
                )

            if not res.text.strip() or "<html" in res.text.lower():
                raise HTTPException(
                    status_code=503,
                    detail="El portal del SENIAT devolvió una respuesta no válida o el sitio está caído",
                )

            root = ET.fromstring(res.text)
            nombre_node = root.find(".//{*}nombre")

            if nombre_node is None or not nombre_node.text:
                raise HTTPException(
                    status_code=404,
                    detail=f"Contribuyente {rif} no encontrado en los registros del SENIAT",
                )

            agente_iva = root.findtext(".//{*}agenteRetencionIVA", default="NO")
            contrib_iva = root.findtext(".//{*}contribuyenteIVA", default="SI")

            return {
                "rif": rif,
                "nombre": nombre_node.text.strip(),
                "es_contribuyente_especial": agente_iva == "SI",
                "agente_retencion": agente_iva,
                "contribuyente_iva": contrib_iva,
            }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Tiempo de espera agotado al conectar con el SENIAT (Servidor inaccesible/Timeout)",
        )
    except httpx.RequestError as e:
        error_detalles = str(e).strip() or type(e).__name__
        raise HTTPException(
            status_code=503,
            detail=f"Error de conexión con el SENIAT: {error_detalles}",
        )
    except ET.ParseError:
        raise HTTPException(
            status_code=502,
            detail="Error al procesar la respuesta de la API del SENIAT (Formato XML inválido)",
        )