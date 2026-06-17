#!/usr/bin/env python3
"""Genera una galería HTML de los builds del experimento, agrupados por LLM,
con enlaces deep-link al viewer (?file=...). Sirve para inspeccionar en la web
el resultado de cada modelo. Salida: scratch/experimento/galeria.html
(servir desde la raíz del repo con `python3 -m http.server 8000`).
"""
import json, html
from pathlib import Path

ROOT = Path("/Users/zhiqian/Desktop/Uni/TFGv2Z")
EXP = ROOT / "scratch" / "experimento"
rows = [json.loads(l) for l in (EXP / "results_decon.jsonl").read_text().splitlines() if l.strip()]

ORDER = ["meta-llama/llama-4-scout", "qwen/qwen3.5-35b-a3b", "google/gemma-4-26b-a4b-it",
         "qwen/qwen3.5-9b", "meta-llama/llama-3.3-70b-instruct", "google/gemma-4-31b-it"]
PROMPTS = []
for r in rows:
    if r["prompt_key"] not in PROMPTS:
        PROMPTS.append(r["prompt_key"])


def safe(m):
    return m.replace("/", "__")


def card(r):
    m, pk = r["model"], r["prompt_key"]
    st = r.get("status")
    ov = r.get("overall")
    pa = r.get("prompt_adherence_total")
    if st == "ok" and isinstance(ov, (int, float)):
        gen = f"{safe(m)}__{pk}"
        fpath = EXP / "builds_decon" / safe(m) / f"{gen}.json"
        if fpath.exists():
            url = f"/viewer/?file=../scratch/experimento/builds_decon/{safe(m)}/{gen}.json"
            badge = f"<span class=ok>overall {ov:.2f}</span>"
            pae = f" · prompt {pa:.2f}" if isinstance(pa, (int, float)) else ""
            return (f'<a class="card ok" href="{url}" target="_blank">'
                    f'<b>{html.escape(pk)}</b>{badge}<small>{pae}</small></a>')
    # failed / no file
    err = html.escape((r.get("error") or st or "?")[:70])
    return (f'<div class="card fail"><b>{html.escape(pk)}</b>'
            f'<span class=bad>{html.escape(st or "?")}</span><small>{err}</small></div>')


parts = ["""<!doctype html><meta charset=utf-8><title>Galería multi-LLM — HomeCraft v2</title>
<style>
body{font:14px system-ui,sans-serif;margin:24px;background:#0f1115;color:#e6e6e6}
h1{font-size:20px}h2{margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}
.meta{color:#9aa0a6;font-size:13px}
.grid{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.card{display:flex;flex-direction:column;gap:2px;min-width:190px;padding:8px 10px;
  border-radius:8px;text-decoration:none;color:#e6e6e6;background:#1a1d23;border:1px solid #2a2e36}
.card.ok:hover{border-color:#4C72B0;background:#1f2530}
.card.fail{opacity:.6}
.ok{color:#7bd88f;font-size:12px}.bad{color:#e06c75;font-size:12px}
small{color:#9aa0a6;font-size:11px}
.note{background:#1a1d23;border:1px solid #2a2e36;border-radius:8px;padding:10px;margin:12px 0}
</style>
<h1>Galería de resultados por LLM — pipeline mejorado (sin fallbacks deterministas)</h1>
<div class="note">Haz clic en un edificio para abrirlo en el <b>viewer 3D</b> (deep-link <code>?file=</code>).
Solo los builds completados tienen enlace; los fallidos muestran el motivo.
Requiere el servidor: <code>python3 -m http.server 8000</code> desde la raíz del repo.</div>
"""]

for m in ORDER:
    rs = [r for r in rows if r["model"] == m]
    if not rs:
        continue
    ok = [r for r in rs if r.get("status") == "ok" and isinstance(r.get("overall"), (int, float))]
    import statistics as st
    ovs = [r["overall"] for r in ok]
    mean = f"{st.mean(ovs):.3f}" if ovs else "—"
    parts.append(f'<h2>{html.escape(m)}</h2>')
    parts.append(f'<div class="meta">completados {len(ok)}/{len(rs)} · overall medio {mean}</div>')
    # order cards by prompt order
    by_pk = {r["prompt_key"]: r for r in rs}
    parts.append('<div class="grid">')
    for pk in PROMPTS:
        if pk in by_pk:
            parts.append(card(by_pk[pk]))
    parts.append('</div>')

out = EXP / "galeria.html"
out.write_text("\n".join(parts), encoding="utf-8")
print("wrote", out, "·", len(rows), "builds")
