#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper del catálogo EPA — PIPELINE MASIVO (Fase B1, MISIÓN 3).

Dos fases desacopladas para máxima resiliencia frente a throttling del CDN de
imágenes de EPA:
  FASE 1 (detalles): por cada categoría, 2 pasadas -> recolecta URLs de ficha
    (pass1) y enriquece con JSON-LD (pass2: sku, nombre, marca, precio USD,
    jerarquía). Escribe data/epa/<cat>.json (NDJSON) DE INMEDIATO, con
    imagen_local=null. Es rápido y NUNCA se bloquea por las imágenes.
  FASE 2 (imágenes): lee cada data/epa/<cat>.json, descarga el original, lo
    convierte a WebP (800px, q80) y actualiza imagen_local. Reanudable por
    checkpoint de archivo físico {sku}.webp (salta el que ya existe).

Concurrencia controlada: asyncio.Semaphore(3) para TODA la E/S de red.
Cortesía/robots.txt: solo URLs limpias, User-Agent real, header From,
reintentos con backoff, respeta 429/503 (Retry-After).

Uso:
  python scrape_epa.py --categorias automotriz
  python scrape_epa.py --categorias banos,pinturas
  python scrape_epa.py --todas
  python scrape_epa.py --todas --limit-cats 3
  python scrape_epa.py --solo-imagenes          # solo re-ejecuta FASE 2
"""
import asyncio
import json
import re
import sys
import time
import random
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image
import io

PROJECT = Path(__file__).resolve().parent.parent
BACKEND = PROJECT / "adrialga-backend"
OUT_DIR = BACKEND / "data" / "epa"          # data/epa/<cat>.json
IMG_DIR = BACKEND / "public" / "productos"  # public/productos/<sku>.webp

BASE = "https://ve.epaenlinea.com"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "es-VE,es;q=0.9",
    "From": "adrialga-dev@example.com",  # identificación honesta del scraper
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

DELAY_MIN, DELAY_MAX = 0.5, 1.0
PAGE_LIMIT = 96
CONCURRENCY = 3  # asyncio.Semaphore(3)
IMG_TIMEOUT = 20   # corto: EPA throttlea el CDN de imágenes -> fast-fail
IMG_RETRIES = 1

CATEGORIAS = [
    "automotriz", "banos", "bodegon", "cocinas", "construccion",
    "decoracion", "electricidad", "electrodomesticos", "exteriores",
    "ferreteria-y-cerrajeria", "herramientas", "lamparas", "limpieza",
    "maderas-y-puertas", "muebles-y-organizacion", "pinturas", "pisos",
    "plomeria", "seguridad",
]


# --------------------------------------------------------------------------- #
# Red de E/S (bloqueante, ejecutada en executor bajo semáforo)
# --------------------------------------------------------------------------- #
def blocking_get(url, timeout=30):
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


def blocking_download(url, timeout=IMG_TIMEOUT):
    for attempt in range(1, IMG_RETRIES + 2):
        try:
            r = SESSION.get(url, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r.content
            if r.status_code in (429, 503):
                time.sleep(int(r.headers.get("Retry-After", 3)) * attempt)
                continue
            print(f"  [img-warn] HTTP {r.status_code} {url}")
            return None
        except Exception as e:
            print(f"  [img-retry {attempt}] {url}: {e}")
            time.sleep(2 * attempt)
    return None


# --------------------------------------------------------------------------- #
# Parseo JSON-LD
# --------------------------------------------------------------------------- #
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
            blocks.append(json.loads(txt))
        except Exception:
            try:
                blocks.append(norm_keys(json.loads(txt)))
            except Exception:
                continue
    return blocks


def _type_of(b):
    t = b.get("@type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return []


def _first(blocks, tipo):
    tipo_l = tipo.lower()
    def match(blk):
        return any(x.lower() == tipo_l for x in _type_of(blk))
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if match(b):
            return b
        graph = b.get("@graph") or b.get("graph")
        if isinstance(graph, list):
            for n in graph:
                if isinstance(n, dict) and match(n):
                    return n
    return None


def breadcrumb_names(bc):
    elems = bc.get("itemListElement") or bc.get("itemlistelement") or []
    names = []
    for e in elems:
        if not isinstance(e, dict):
            continue
        nm = e.get("name")
        if not nm and isinstance(e.get("item"), dict):
            nm = e["item"].get("name")
        if nm:
            names.append(nm)
    return names


def collapse_dups(seq):
    out = []
    for n in seq:
        if out and out[-1].strip().lower() == n.strip().lower():
            continue
        out.append(n)
    return out


def original_image(url):
    if not url:
        return None
    parts = url.split("/cache/")
    if len(parts) != 2:
        return url
    base, rest = parts
    segs = rest.split("/")[1:]
    return base + "/" + "/".join(segs)


def sanitize(sku):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(sku).strip())


# --------------------------------------------------------------------------- #
# Pass 1 — recolectar URLs de fichas por categoría
# --------------------------------------------------------------------------- #
def pass1_collect(cat):
    urls, seen = [], set()
    p = 1
    MAX_PAGES = 80
    while p <= MAX_PAGES:
        url = f"{BASE}/productos/{cat}.html?product_list_limit={PAGE_LIMIT}&p={p}"
        r = blocking_get(url)
        if not r:
            break
        soup = BeautifulSoup(r.text, "lxml")
        links = soup.select("li.product-item a.product-item-link") or soup.select("a.product-item-link")
        if not links:
            print(f"    [pass1] {cat} p={p}: sin productos, fin.")
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
            if "?cat=" in href or "catalog/product/view" in href:
                continue
            urls.append(href)
            new += 1
        print(f"    [pass1] {cat} p={p}: +{new} (total {len(urls)})")
        if not soup.select_one("a.next"):
            break
        p += 1
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    return urls


# --------------------------------------------------------------------------- #
# Pass 2 — enriquecer una ficha (detalle SIN imagen)
# --------------------------------------------------------------------------- #
def pass2_detail(url):
    r = blocking_get(url)
    if not r:
        return None
    blocks = extract_ld_json(r.text)
    prod = _first(blocks, "Product")
    bc = _first(blocks, "BreadcrumbList")
    if not prod:
        return None
    sku = prod.get("sku") or prod.get("id")
    name = prod.get("name")
    if not sku or not name:
        return None

    price = prod.get("price")
    currency = prod.get("priceCurrency") or prod.get("pricecurrency")
    off = prod.get("offers")
    if isinstance(off, dict):
        price = price if price is not None else off.get("price")
        currency = currency or off.get("priceCurrency") or off.get("pricecurrency")
    elif isinstance(off, list) and off:
        o0 = off[0]
        price = price if price is not None else o0.get("price")
        currency = currency or o0.get("priceCurrency") or o0.get("pricecurrency")

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
        hier = collapse_dups(clean)

    return {
        "sku": str(sku).strip(),
        "nombre": name.strip(),
        "marca": (brand or "").strip() or None,
        "precio_usd": float(price) if price not in (None, "") else None,
        "moneda": (currency or "USD"),
        "url_ficha": url,
        "imagen_original": img,
        "imagen_local": None,   # FASE 2 la llena
        "jerarquia": hier,
    }


def save_webp(sku, img_bytes):
    fname = sanitize(sku) + ".webp"
    dest = IMG_DIR / fname
    if dest.exists() and dest.stat().st_size > 0:
        return f"/productos/{fname}"
    try:
        im = Image.open(io.BytesIO(img_bytes))
        im = im.convert("RGBA") if im.mode in ("RGBA", "LA") else im.convert("RGB")
        if im.mode == "RGBA":
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        im.thumbnail((800, 800))
        im.save(dest, "WEBP", quality=80, method=4)
        return f"/productos/{fname}"
    except Exception as e:
        print(f"  [img-err] {sku}: {e}")
        if dest.exists():
            dest.unlink()
        return None


# --------------------------------------------------------------------------- #
# FASE 1 — detalles por categoría (escribe NDJSON de inmediato)
# --------------------------------------------------------------------------- #
async def scrape_category_details(loop, sem, cat, done_urls):
    print(f"\n== [FASE1] Categoría: {cat} ==")
    urls = pass1_collect(cat)
    if not urls:
        print(f"  [!] {cat}: 0 fichas.")
        return 0

    out_file = OUT_DIR / f"{cat}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    write_lock = asyncio.Lock()
    count = 0

    async def handle(url):
        nonlocal count
        async with sem:
            rec = await loop.run_in_executor(None, pass2_detail, url)
        if not rec:
            return
        async with write_lock:
            with open(out_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            count += 1

    pending = [u for u in urls if u not in done_urls]
    print(f"  fichas={len(urls)} nuevas={len(pending)} (checkpoint={len(urls)-len(pending)})")
    await asyncio.gather(*[handle(u) for u in pending])
    print(f"  == [FASE1] {cat}: detalles={count} -> {out_file}")
    return count


# --------------------------------------------------------------------------- #
# FASE 2 — imágenes WebP (resumible por checkpoint de archivo físico)
# --------------------------------------------------------------------------- #
async def fase2_imagenes(loop, sem):
    print("\n== [FASE2] Descarga de imágenes WebP ==")
    if not OUT_DIR.exists():
        print("  no hay data/epa/*.json todavía.")
        return
    archivos = sorted(OUT_DIR.glob("*.json"))
    total = 0
    for f in archivos:
        recs = []
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    recs.append(json.loads(line))
        except Exception:
            continue
        if not recs:
            continue

        async def proc(rec):
            nonlocal total
            sku = rec.get("sku")
            img_url = rec.get("imagen_original")
            if not sku or not img_url:
                return
            dest = IMG_DIR / (sanitize(sku) + ".webp")
            if dest.exists() and dest.stat().st_size > 0:
                rec["imagen_local"] = f"/productos/{dest.name}"
                return
            async with sem:
                data = await loop.run_in_executor(None, blocking_download, img_url)
            if data:
                rel = await loop.run_in_executor(None, save_webp, sku, data)
                rec["imagen_local"] = rel
            else:
                rec["imagen_local"] = None

        await asyncio.gather(*[proc(rec) for rec in recs])
        # Reescribir el archivo con imagen_local actualizado
        with open(f, "w", encoding="utf-8") as out:
            for rec in recs:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        ok = sum(1 for r in recs if r.get("imagen_local"))
        total += ok
        print(f"  [FASE2] {f.name}: {ok}/{len(recs)} imágenes ok")

    print(f"== [FASE2] total imágenes locales = {total} ==")


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #
def load_done_urls(cat):
    done = set()
    f = OUT_DIR / f"{cat}.json"
    if f.exists():
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        done.add(json.loads(line)["url_ficha"])
                    except Exception:
                        pass
        except Exception:
            pass
    return done


async def main_async(solo_imagenes=False):
    cats = parse_cats()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(CONCURRENCY)

    if not solo_imagenes:
        for cat in cats:
            done = load_done_urls(cat)
            await scrape_category_details(loop, sem, cat, done)
            time.sleep(1.0)
    await fase2_imagenes(loop, sem)
    print("\n== FIN == ")


def parse_cats():
    args = sys.argv[1:]
    if "--solo-imagenes" in args:
        return []  # FASE2 usa todos los archivos existentes
    if "--todas" in args:
        idx = args.index("--todas")
        limit = None
        if len(args) > idx + 1 and args[idx + 1].startswith("--limit-cats"):
            limit = int(args[idx + 1].split("=")[1])
        return CATEGORIAS[:limit] if limit else CATEGORIAS
    cats: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--categorias="):
            val = a.split("=", 1)[1]
            cats = [c.strip() for c in val.split(",") if c.strip()]
        elif a == "--categorias":
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                cats = [c.strip() for c in args[i + 1].split(",") if c.strip()]
                i += 1
        i += 1
    if not cats:
        cats = ["automotriz"]
    return cats


if __name__ == "__main__":
    asyncio.run(main_async(solo_imagenes="--solo-imagenes" in sys.argv))
