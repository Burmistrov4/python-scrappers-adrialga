#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper del catálogo EPA — categoría AUTOMOTRIZ (Fase B1, prueba de humo).
Estrategia de 2 pasadas (HTML server-rendered, CloudFront sin challenge):
  Pass 1: recorre /productos/automotriz.html (limit=96, pagina ?p=) y extrae las
          URLs de ficha (anclas a.product-item-link dentro de li.product-item).
  Pass 2: por cada ficha parsea el JSON-LD (Product + BreadcrumbList + Brand +
          Offer) para sku, nombre, marca, precio USD, jerarquia e imagen.
Descarga el ORIGINAL de la imagen (quita /cache/{hash}/) a
  adrialga-backend/public/productos/{sku}.jpg
Escribe adrialga-backend/data/automotriz.json (NDJSON, 1 registro por producto).

Cortesía / robots.txt:
  - Solo URLs limpias (/productos/x.html, fichas .html). NUNCA ?cat=/?marca=/?colour=/?price=.
  - User-Agent real + cabecera From de identificación.
  - Delay 0.8-1.5 s, reintentos con backoff, respeta 429/503 (Retry-After).
"""
import json
import re
import time
import random
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image
import io

PROJECT = Path(r"C:/Users/Loro/Desktop/Cuarto Semestre/3. Analisis de Sistemas II/Adrialga_Sistema_Renovado")
BACKEND = PROJECT / "adrialga-backend"
OUT_JSON = BACKEND / "data" / "automotriz.json"
IMG_DIR = BACKEND / "public" / "productos"

BASE = "https://ve.epaenlinea.com"
ROOT = f"{BASE}/productos/automotriz.html"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "es-VE,es;q=0.9",
    "From": "adrialga-dev@example.com",  # identificación honesta del scraper
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

DELAY_MIN, DELAY_MAX = 0.8, 1.5
PAGE_LIMIT = 96


def get(url, timeout=30):
    for attempt in range(1, 6):
        try:
            r = SESSION.get(url, timeout=timeout)
            if r.status_code in (429, 503):
                wait = int(r.headers.get("Retry-After", 5)) * attempt
                print(f"  [rate] {r.status_code} {url} -> espero {wait}s")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                print(f"  [warn] HTTP {r.status_code} {url}")
                return None
            return r
        except Exception as e:
            print(f"  [retry {attempt}] {url}: {e}")
            time.sleep(2 * attempt)
    return None


def norm_keys(obj):
    if isinstance(obj, dict):
        return {str(k).lower(): norm_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [norm_keys(x) for x in obj]
    return obj


def extract_ld_json(html):
    soup = BeautifulSoup(html, "lxml")
    blocks = []
    for tag in soup.find_all("script", type="application/ld+json"):
        txt = tag.string or tag.get_text()
        if not txt:
            continue
        try:
            blocks.append(norm_keys(json.loads(txt)))
        except Exception:
            continue
    return blocks


def _first(b, tipo):
    if isinstance(b, dict):
        if b.get("@type") == tipo:
            return b
        if isinstance(b.get("graph"), list):
            for n in b["graph"]:
                if isinstance(n, dict) and n.get("@type") == tipo:
                    return n
    return None


def breadcrumb_names(bc):
    elems = bc.get("itemlistelement") or bc.get("itemlistelement") or []
    return [e.get("name") for e in elems if isinstance(e, dict) and e.get("name")]


def original_image(url):
    """Quita el segmento /cache/{hash}/ de la URL de imagen de EPA."""
    if not url:
        return None
    parts = url.split("/cache/")
    if len(parts) != 2:
        return url
    base, rest = parts
    segs = rest.split("/")[1:]  # descarta el hash
    return base + "/" + "/".join(segs)


def pass1_collect():
    urls, seen = [], set()
    p = 1
    while True:
        url = f"{ROOT}?product_list_limit={PAGE_LIMIT}&p={p}"
        r = get(url)
        if not r:
            break
        soup = BeautifulSoup(r.text, "lxml")
        links = soup.select("li.product-item a.product-item-link") or soup.select("a.product-item-link")
        if not links:
            print(f"  [pass1] p={p}: sin productos, fin.")
            break
        new = 0
        for a in links:
            href = a.get("href")
            if not href:
                continue
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = BASE + href
            if href in seen:
                continue
            seen.add(href)
            urls.append(href)
            new += 1
        print(f"  [pass1] p={p}: +{new} (total {len(urls)})")
        if new < PAGE_LIMIT and not soup.select_one("a.next"):
            break
        p += 1
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    return urls


def pass2_detail(url):
    r = get(url)
    if not r:
        return None
    blocks = extract_ld_json(r.text)
    prod = _first(blocks, "product") or _first(blocks, "products")
    bc = _first(blocks, "breadcrumblist")
    if not prod:
        return None
    sku = prod.get("sku") or prod.get("id")
    name = prod.get("name")
    if not sku or not name:
        return None

    price = prod.get("price")
    currency = prod.get("pricecurrency")
    off = prod.get("offers")
    if isinstance(off, dict):
        price = price if price is not None else off.get("price")
        currency = currency or off.get("pricecurrency")
    elif isinstance(off, list) and off:
        price = price if price is not None else off[0].get("price")
        currency = currency or off[0].get("pricecurrency")

    brand = prod.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    soup = BeautifulSoup(r.text, "lxml")
    og = soup.find("meta", property="og:image")
    og_url = og.get("content") if og else None
    img = original_image(og_url) or (prod.get("image")[0] if isinstance(prod.get("image"), list) else prod.get("image"))

    hier = []
    if bc:
        names = breadcrumb_names(bc)
        clean = [n for n in names if n and n.lower() not in ("inicio", "productos")]
        if clean and clean[-1].lower() == name.lower():
            clean = clean[:-1]
        hier = clean

    return {
        "sku": str(sku).strip(),
        "nombre": name.strip(),
        "marca": (brand or "").strip() or None,
        "precio_usd": float(price) if price not in (None, "") else None,
        "moneda": (currency or "USD"),
        "url_ficha": url,
        "imagen_original": img,
        "jerarquia": hier,
    }


def download_image(rec):
    sku = rec["sku"]
    img_url = rec.get("imagen_original")
    if not img_url:
        return None
    fname = re.sub(r"[^A-Za-z0-9._-]", "_", sku) + ".jpg"
    dest = IMG_DIR / fname
    if dest.exists() and dest.stat().st_size > 0:
        return f"/productos/{fname}"
    r = get(img_url, timeout=40)
    if not r or not r.content:
        return None
    try:
        im = Image.open(io.BytesIO(r.content))
        im.thumbnail((800, 800))
        im.convert("RGB").save(dest, "JPEG", quality=82)
    except Exception:
        dest.write_bytes(r.content)
    return f"/productos/{fname}"


def main():
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    print("== PASS 1: recolectar URLs de fichas ==")
    urls = pass1_collect()
    print(f"Total fichas: {len(urls)}")
    print("== PASS 2: enriquecer + descargar imagen ==")
    records, ok, skip, img_ok = [], 0, 0, 0
    for i, u in enumerate(urls, 1):
        rec = pass2_detail(u)
        if not rec:
            skip += 1
            print(f"  [{i}/{len(urls)}] sin JSON-LD, skip {u}")
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            continue
        rel = download_image(rec)
        rec["imagen_local"] = rel
        if rel:
            img_ok += 1
        records.append(rec)
        ok += 1
        if i % 10 == 0:
            print(f"  [{i}/{len(urls)}] ok={ok} skip={skip} img={img_ok}")
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\n== FIN == productos={ok} skip={skip} imagenes={img_ok} -> {OUT_JSON}")


if __name__ == "__main__":
    main()
