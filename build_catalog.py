#!/usr/bin/env python3
"""
Genera catalogo.csv / catalogo.json con todos los e-books de tiendalibros.com
(precios para Argentina en ARS), leyendo la API REST pública que usa la propia
tienda (Deyel /v1.0) con el token de visitante anónimo que entrega la home.

Fuente:
  - DIST1695739934 ("Distribución por país"): título, autor, ISBN, precio, estado
    filtrado country=AR, money=ARS (lo mismo que usa su feed de Meta/Google).
  - CRM_PRODUCT ("Producto"): linkImage (tapa) y estado del producto.

Uso: python3 build_catalog.py [--out DIR] [--sleep 0.5] [--limit-pages N]
Solo lectura (GET). No necesita usuario ni clave.
"""
import argparse, csv, json, os, re, sys, time, urllib.parse, urllib.request, http.cookiejar
from datetime import datetime, timezone

BASE = "https://tiendalibros.com"
UA = "tiendalibros-catalog-feed/1.0 (+garpa.ar)"
DIST = "DIST1695739934"
PROD = "CRM_PRODUCT"

class Api:
    def __init__(self, sleep):
        self.sleep = sleep
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.token = None
        self.refresh_token()

    def refresh_token(self):
        req = urllib.request.Request(BASE + "/", headers={"User-Agent": UA})
        html = self.op.open(req, timeout=60).read().decode("latin-1")
        m = re.search(r'id="_t"[^>]*value="([^"]+)"', html)
        if not m:
            raise RuntimeError("No se encontró el token anónimo en la home")
        self.token = m.group(1)

    def get(self, path, params):
        url = BASE + path + "?" + urllib.parse.urlencode(params, safe=":,|=")
        for attempt in range(6):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json",
                                                          "Authorization": "Bearer " + self.token})
                with self.op.open(req, timeout=120) as r:
                    data = json.loads(r.read().decode("utf-8"))
                time.sleep(self.sleep)
                return data
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    self.refresh_token()
                wait = 5 * (attempt + 1)
                print(f"  HTTP {e.code} en {url[:120]} -> reintento en {wait}s", file=sys.stderr)
                time.sleep(wait)
            except Exception as e:
                wait = 5 * (attempt + 1)
                print(f"  {e!r} -> reintento en {wait}s", file=sys.stderr)
                time.sleep(wait)
        raise RuntimeError("Falló " + url)

def isbn_ok(s):
    s = re.sub(r"[^0-9Xx]", "", s or "")
    if len(s) == 13 and s[:3] in ("978", "979"):
        tot = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s[:12]))
        return s if (10 - tot % 10) % 10 == int(s[12]) else ""
    if len(s) == 10:
        try:
            tot = sum((10 - i) * (10 if c in "Xx" else int(c)) for i, c in enumerate(s))
        except ValueError:
            return ""
        return s.upper() if tot % 11 == 0 else ""
    return ""

def fmt_price(v):
    """Pesos enteros, sin decimales."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return str(int(f + 0.5))

TEST_TITLE = re.compile(r"^\s*(publication\s*\w*|test|prueba|libro de prueba|demo)\s*$", re.I)

def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--page-size", type=int, default=2000)
    ap.add_argument("--limit-pages", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    api = Api(a.sleep)
    t0 = time.time()

    # 1) Precios AR / ARS
    rows, page, total = {}, 1, None
    while True:
        d = api.get(f"/v1.0/forms/{DIST}/instances",
                    {"search": "country=eq:AR,money=eq:ARS", "page-number": page, "per-page": a.page_size})
        total = d["paging"]["total-items"]; pages = d["paging"]["pages"]
        for i in d["instances"]:
            rows[i["id"]] = i
        print(f"DIST página {page}/{pages}: {len(rows)}/{total}", file=sys.stderr)
        if page >= pages or not d["instances"] or (a.limit_pages and page >= a.limit_pages):
            break
        page += 1
    if not a.limit_pages and len(rows) < total:
        print(f"AVISO: se leyeron {len(rows)} filas de precio de {total} (paginación inestable)", file=sys.stderr)

    # 2) Una fila por libro: preferir la activa, luego la más reciente
    def rank(r):
        active = str(r.get("cdState")) == "1" and str(r.get("priceState")) == "1"
        return (active, int(r.get("dtLastUpdate") or 0))
    best = {}
    for r in rows.values():
        b = str(r.get("book") or "")
        if b and (b not in best or rank(r) > rank(best[b])):
            best[b] = r
    print(f"Libros únicos con precio AR/ARS: {len(best)}", file=sys.stderr)
    if os.environ.get("TL_DEBUG"):
        keep = ["id","book","isbn","finalPrice","price","discountPrice","cdState","cdStatus","priceState","priceType","dtLastUpdate","dsName","author","languageCode"]
        json.dump([{k: r.get(k) for k in keep} for r in rows.values()], open(os.path.join(a.out, "_debug_dist.json"), "w"), ensure_ascii=False)

    # 3) Datos del producto (tapa, estado) en lotes
    prods, ids = {}, sorted(best, key=int)
    B = 150
    for k in range(0, len(ids), B):
        chunk = ids[k:k + B]
        d = api.get(f"/v1.0/forms/{PROD}/instances",
                    {"search": "idProduct=in:" + "|".join(chunk), "page-number": 1, "per-page": B})
        for p in d.get("instances", []):
            prods[str(p["idProduct"])] = {"linkImage": p.get("linkImage"), "cdState": p.get("cdState"),
                                          "dsName": p.get("dsName"), "dsCode": p.get("dsCode")}
        if (k // B) % 20 == 0:
            print(f"PRODUCT {k + len(chunk)}/{len(ids)}", file=sys.stderr)

    # 4) Armar salida
    out = []
    for b in ids:
        r, p = best[b], prods.get(b, {})
        autor = clean(r.get("author"))
        if autor.lower() == "autor no informado":
            autor = ""
        disponible = (str(r.get("cdState")) == "1" and str(r.get("priceState")) == "1"
                      and str(p.get("cdState", "")) == "1")
        out.append({
            "titulo": clean(r.get("dsName") or p.get("dsName")),
            "autor": autor,
            "precio": fmt_price(r.get("finalPrice")),
            "link": f"{BASE}/pages/mainHome?target=detail&idProduct={b}",
            "foto": p.get("linkImage") or "",
            "isbn": isbn_ok(r.get("isbn") or p.get("dsCode")),
            "disponible": "si" if disponible else "no",
        })
    n_all = len(out)
    out = [x for x in out if x["disponible"] == "si" and not TEST_TITLE.match(x["titulo"])]
    print(f"Filtrados (no disponibles / de prueba): {n_all - len(out)}", file=sys.stderr)
    out.sort(key=lambda x: x["titulo"].lower())

    cols = ["titulo", "autor", "precio", "link", "foto", "isbn", "disponible"]
    tmp = os.path.join(a.out, "catalogo.csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(out)
    os.replace(tmp, os.path.join(a.out, "catalogo.csv"))
    meta = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "moneda": "ARS",
            "fuente": BASE, "total": len(out), "libros": out}
    tmp = os.path.join(a.out, "catalogo.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(a.out, "catalogo.json"))

    n = len(out)
    st = lambda f: sum(1 for x in out if f(x))
    print(json.dumps({"filas": n, "disponible_si": st(lambda x: x["disponible"] == "si"),
                      "sin_isbn": st(lambda x: not x["isbn"]), "sin_foto": st(lambda x: not x["foto"]),
                      "sin_autor": st(lambda x: not x["autor"]), "sin_precio": st(lambda x: not x["precio"]),
                      "precio_0": st(lambda x: x["precio"] == "0"),
                      "sin_producto": sum(1 for b in ids if b not in prods),
                      "segundos": round(time.time() - t0)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
