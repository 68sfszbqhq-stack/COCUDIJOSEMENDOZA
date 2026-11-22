"""Genera referencias.html a partir del repositorio de referencias de Aula RAF.

Uso: python3 scripts/generar_referencias.py ~/proyectos/aula-raf/repositorio/referencias.json
Omite documentos internos, rutas académicas y fuentes marcadas sin utilidad.
"""
import html, json, sys
from collections import defaultdict

OMITIR_TIPOS = {"documento interno", "ruta académica"}
refs = json.load(open(sys.argv[1], encoding="utf-8"))
grupos = defaultdict(list)
for r in refs:
    if r.get("tipo") in OMITIR_TIPOS or r.get("archivo_local") or "sin utilidad" in (r.get("estado") or ""):
        continue
    materias = r.get("materias") or ["General RAF"]
    grupos[materias[0] if len(materias) == 1 else "Varias materias"].append(r)

def estado(e):
    e = e or ""
    if e.startswith("leído"): return "Leído completo"
    if "PubMed" in e: return "Resumen verificado en PubMed"
    if "YouTube" in e: return "Video verificado; contenido por revisar"
    if "sin consultar" in e: return "Citado en un programa, sin consultar"
    if e.startswith("verificado"): return "Verificado en fuente oficial"
    return e.capitalize()

orden = ["Control de la Carga Física", "Activación en la Persona con Discapacidad", "Metodología de la Investigación I", "Varias materias", "General RAF"]
secciones, total = [], 0
for g in sorted(grupos, key=lambda g: orden.index(g) if g in orden else 99):
    items = sorted(grupos[g], key=lambda r: r["apa"].lower())
    total += len(items)
    lis = []
    for r in items:
        enlace = f' <a href="{html.escape(r["url"])}" target="_blank" rel="noopener">Abrir</a>' if r.get("url") else ""
        lis.append(f'<li><span class="apa">{html.escape(r["apa"])}</span>{enlace}<br><span class="meta">{html.escape(r.get("tipo") or "")} · {estado(r.get("estado"))} · consultado {html.escape(r.get("fecha_consulta") or "s. f.")}</span></li>')
    secciones.append(f'<h2>{html.escape(g)} <small>({len(items)})</small></h2>\n<ul>\n' + "\n".join(lis) + "\n</ul>")

pagina = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Repositorio de referencias · PLE José Roberto Mendoza</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;max-width:900px;margin:0 auto;padding:32px 20px;color:#2C3E50;line-height:1.55;background:#F4F7F6}}
h1{{color:#C0392B;margin-bottom:4px}} h2{{margin-top:36px;border-bottom:3px solid #C0392B;padding-bottom:4px}} small{{color:#777;font-weight:400}}
ul{{list-style:none;padding:0}} li{{background:#fff;margin:10px 0;padding:12px 16px;border-radius:10px;border-left:5px solid #0f766e}}
.apa{{padding-left:0}} .meta{{font-size:.85rem;color:#666}} a{{color:#0f766e;font-weight:700}}
.volver{{display:inline-block;margin-bottom:20px}} footer{{margin-top:40px;font-size:.85rem;color:#555}}
</style></head><body>
<a class="volver" href="index.html">← Volver a mi PLE</a>
<h1>Repositorio de referencias</h1>
<p>Fuentes que reuní para mis materias de la Licenciatura en Readaptación y Activación Física (BUAP), en formato APA 7 y con su enlace. Cada una dice si la leí completa, si verifiqué su resumen o si solo la vi citada. {total} referencias.</p>
{chr(10).join(secciones)}
<footer>Recopilación de José Roberto Mendoza Mendoza, con licencia <a href="https://creativecommons.org/licenses/by-sa/4.0/deed.es" target="_blank" rel="license">CC BY-SA 4.0</a>. Cada obra citada conserva los derechos de sus autores.</footer>
</body></html>
"""
open("referencias.html", "w", encoding="utf-8").write(pagina)
print(f"referencias.html: {total} referencias en {len(grupos)} grupos")
