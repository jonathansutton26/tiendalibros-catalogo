# Feed de catálogo de e-books de tiendalibros.com (para garpa.ar)

`build_catalog.py` lee la API pública de la tienda (Deyel `/v1.0`, token de visitante anónimo)
y genera `output/catalogo.csv` y `output/catalogo.json` con columnas:
titulo, autor, precio (ARS), link, foto, isbn, disponible (si/no).

- Precios: tabla "Distribución por país" (DIST1695739934) con country=AR, money=ARS.
- Tapa: CRM_PRODUCT.linkImage (CDN de Cantook/Libranda).
- Solo se publican libros disponibles (disponible siempre "si"); precios redondeados a pesos enteros; se excluyen productos de prueba.
- ISBN solo si es un ISBN-13/10 válido (si no, vacío).

Correr: `python3 build_catalog.py` (~25 min, solo GETs, ~1.000 requests con pausa de 0,5 s).
Workflow diario para GitHub Pages en `.github/workflows/catalogo.yml`.
