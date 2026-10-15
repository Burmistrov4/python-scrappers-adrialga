#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, sys
import requests
from bs4 import BeautifulSoup

BASE = "https://ve.epaenlinea.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept-Language": "es-VE,es;q=0.9", "From": "adrialga-dev@example.com"}
S = requests.Session(); S.headers.update(H)

url = sys.argv[1] if len(sys.argv) > 1 else f"{BASE}/aceite-mineral-20w50-1-galon-inca.html"
r = S.get(url, timeout=30)
print("HTTP", r.status_code, "len", len(r.text))
soup = BeautifulSoup(r.text, "lxml")
tags = soup.find_all("script", type="application/ld+json")
print("ld+json script tags found:", len(tags))
for i, t in enumerate(tags):
    txt = t.string or t.get_text()
    print(f"---- tag {i} (len {len(txt) if txt else 0}) ----")
    print(txt[:3000] if txt else "(empty)")
    print("---- end tag", i, "----")
# also show og:image and product-item meta
og = soup.find("meta", property="og:image")
print("og:image:", og.get("content") if og else None)
