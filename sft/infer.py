#!/usr/bin/env python3
"""Inferencia / prueba del modelo SFT entrenado con Unsloth.

Carga el adapter LoRA sobre el base 4-bit, genera el JSON del edificio para una
descripción, e intenta parsearlo (y validarlo con tools/validate_building.py).

Uso:
  python sft/infer.py --prompt "A small round stone tower with a conical roof."
  python sft/infer.py --prompt-file desc.txt --out build.json --validate
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template
from transformers import TextStreamer

from common import build_messages

ROOT = Path(__file__).resolve().parent.parent


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", default=str(ROOT / "sft" / "outputs" / "lora_adapter"),
                    help="ruta del adapter LoRA entrenado (o un modelo fusionado)")
    ap.add_argument("--chat-template", default="gemma2")
    ap.add_argument("--max-seq-len", type=int, default=8192)
    ap.add_argument("--max-new-tokens", type=int, default=8192)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--prompt-file", default=None)
    ap.add_argument("--out", default=None, help="guardar el JSON generado")
    ap.add_argument("--validate", action="store_true",
                    help="validar con tools/validate_building.py")
    ap.add_argument("--no-stream", action="store_true")
    return ap.parse_args()


def main():
    args = parse_args()
    if args.prompt_file:
        description = Path(args.prompt_file).read_text().strip()
    elif args.prompt:
        description = args.prompt
    else:
        sys.exit("Da --prompt o --prompt-file")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.adapter,
        max_seq_length=args.max_seq_len,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model)
    tokenizer = get_chat_template(tokenizer, chat_template=args.chat_template)

    msgs = build_messages(description)   # sin completion → add_generation_prompt
    inputs = tokenizer.apply_chat_template(
        msgs, tokenize=True, add_generation_prompt=True, return_tensors="pt"
    ).to(model.device)

    streamer = None if args.no_stream else TextStreamer(tokenizer, skip_prompt=True)
    out = model.generate(
        input_ids=inputs,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        do_sample=args.temperature > 0,
        streamer=streamer,
    )
    text = tokenizer.decode(out[0][inputs.shape[1]:], skip_special_tokens=True)

    # Intentar extraer el JSON (el modelo puede envolverlo en ```).
    raw = text.strip()
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip() if raw.count("```") >= 2 else raw
    try:
        doc = json.loads(raw)
        ok = isinstance(doc, dict) and "voxels" in doc and "block_palette" in doc
        print(f"\n[json] parseado OK={ok}  voxels={len(doc.get('voxels', []))}  "
              f"paleta={len(doc.get('block_palette', {}))}")
    except Exception as e:
        print(f"\n[json] NO parsea: {e}")
        doc = None

    if doc and args.out:
        Path(args.out).write_text(json.dumps(doc))
        print(f"[out] {args.out}")

    if doc and args.validate:
        tmp = Path(args.out) if args.out else (ROOT / "sft" / "_infer_tmp.json")
        d = dict(doc); d.setdefault("description", description)
        tmp.write_text(json.dumps(d))
        p = subprocess.run(["python3", "tools/validate_building.py", str(tmp)],
                           cwd=str(ROOT), capture_output=True, text=True)
        print("[validate]", (p.stdout + p.stderr).strip().splitlines()[-1])


if __name__ == "__main__":
    main()
