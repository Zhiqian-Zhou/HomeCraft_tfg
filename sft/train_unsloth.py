#!/usr/bin/env python3
"""SFT con Unsloth (QLoRA 4-bit) — texto → JSON de edificio voxel.

Optimizado para una sola RTX 5090 (32 GB, Blackwell sm_120). Por defecto
entrena Gemma-2-9B-it en 4-bit con LoRA, gradient checkpointing de Unsloth,
optimizador de 8-bit y entrenamiento SOLO sobre la respuesta (el JSON).

Dataset: scratch/sft/sft_train.jsonl + sft_val.jsonl (formato {prompt, completion}),
generados por tools/build_sft_dataset.py.

IMPORTANTE — secuencias largas:
  Las completion del experimento pueden superar 100k tokens. No se truncan
  (rompería el JSON); se FILTRAN las que no caben en --max-seq-len, y se
  reporta cuántas quedan por fuente. Sube --max-seq-len (más VRAM) o limita el
  dataset con `build_sft_dataset.py --exp-voxel-cap N` si quieres entrenar con
  menos edificios pero más largos.

Uso típico (5090):
  python sft/train_unsloth.py                          # gemma-2-9b, seq 8192
  python sft/train_unsloth.py --max-seq-len 16384      # más cobertura, más VRAM
  python sft/train_unsloth.py --model unsloth/gemma-3-4b-it-bnb-4bit --max-seq-len 24576
  python sft/train_unsloth.py --merge                  # exporta también pesos 16-bit fusionados
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path

# unsloth debe importarse ANTES que transformers/trl para aplicar sus parches.
# FastModel es el cargador universal: soporta modelos de solo texto Y multimodales
# (gemma-3/gemma-4, qwen-vl/qwen3.5...). Para texto-solo entrenamos solo las
# capas de lenguaje.
from unsloth import FastModel, is_bfloat16_supported
from unsloth.chat_templates import get_chat_template, train_on_responses_only
from datasets import load_dataset
from trl import SFTTrainer, SFTConfig
import torch

from common import build_messages, response_markers, detect_response_markers

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "scratch" / "sft"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # Modelo
    ap.add_argument("--model", default="unsloth/gemma-2-9b-it-bnb-4bit",
                    help="modelo base 4-bit de Unsloth (gemma-2-9b por defecto)")
    ap.add_argument("--chat-template", default="gemma2",
                    help="plantilla de chat de Unsloth (gemma2 / gemma-3 / qwen-2.5 / qwen3)")
    ap.add_argument("--instruction-part", default=None,
                    help="override del marcador de prompt (si no, según la plantilla)")
    ap.add_argument("--response-part", default=None,
                    help="override del marcador de respuesta (si no, según la plantilla)")
    ap.add_argument("--max-seq-len", type=int, default=8192,
                    help="longitud máxima de secuencia; filtra ejemplos más largos")
    # LoRA
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=16)
    ap.add_argument("--lora-dropout", type=float, default=0.0)
    # Entrenamiento
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--max-steps", type=int, default=0,
                    help="si >0, limita a N pasos (smoke-test); ignora --epochs")
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch", type=int, default=1, help="batch por dispositivo")
    ap.add_argument("--grad-accum", type=int, default=16,
                    help="acumulación de gradiente (batch efectivo = batch*grad_accum)")
    ap.add_argument("--warmup-ratio", type=float, default=0.05)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--seed", type=int, default=3407)
    # Datos / salida
    ap.add_argument("--train-file", default=str(DATA / "sft_train.jsonl"))
    ap.add_argument("--val-file", default=str(DATA / "sft_val.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "sft" / "outputs"))
    ap.add_argument("--eval", action="store_true",
                    help="evaluar en validación cada N pasos (usa más VRAM)")
    ap.add_argument("--response-only", action="store_true",
                    help="enmascarar el prompt y entrenar solo la respuesta "
                         "(requiere marcadores válidos; por defecto OFF=secuencia completa)")
    ap.add_argument("--merge", action="store_true",
                    help="al acabar, guardar también pesos 16-bit fusionados (despliegue)")
    ap.add_argument("--save-gguf", default=None,
                    help="cuantización GGUF a exportar (p.ej. q4_k_m); requiere llama.cpp")
    return ap.parse_args()


def main():
    args = parse_args()
    Path(args.out).mkdir(parents=True, exist_ok=True)

    # ---- Modelo base (4-bit) -------------------------------------------------
    model, tokenizer = FastModel.from_pretrained(
        model_name=args.model,
        max_seq_length=args.max_seq_len,
        dtype=None,                # auto: bf16 en Blackwell/Ampere+
        load_in_4bit=True,
        full_finetuning=False,
    )

    # ---- Adaptadores LoRA ----------------------------------------------------
    # finetune_vision_layers=False → SFT de solo texto sobre modelos multimodales.
    model = FastModel.get_peft_model(
        model,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        finetune_vision_layers=False,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        use_gradient_checkpointing="unsloth",   # clave para secuencias largas en 32GB
        random_state=args.seed,
        use_rslora=False,
    )

    # Plantilla de chat: si el tokenizer ya trae una (modelos -it), la usamos;
    # si no, la aplicamos por nombre.
    if getattr(tokenizer, "chat_template", None):
        print(f"[chat] usando plantilla integrada del modelo ({args.chat_template} como familia)")
    else:
        tokenizer = get_chat_template(tokenizer, chat_template=args.chat_template)

    # ---- Dataset → texto con chat-template -----------------------------------
    # En modelos multimodales (gemma4, qwen3_5) `tokenizer` es un Processor;
    # para contar tokens de texto usamos su tokenizer interno.
    text_tok = getattr(tokenizer, "tokenizer", tokenizer)

    def to_text(batch):
        texts = []
        for p, c in zip(batch["prompt"], batch["completion"]):
            convo = build_messages(p, c)
            texts.append(tokenizer.apply_chat_template(
                convo, tokenize=False, add_generation_prompt=False))
        return {"text": texts}

    def add_len(batch):
        toks = text_tok(batch["text"], add_special_tokens=False)["input_ids"]
        return {"n_tokens": [len(t) for t in toks]}

    data_files = {"train": args.train_file}
    if Path(args.val_file).exists():
        data_files["validation"] = args.val_file
    ds = load_dataset("json", data_files=data_files)

    for split in ds:
        ds[split] = ds[split].map(to_text, batched=True,
                                  remove_columns=[c for c in ds[split].column_names
                                                  if c not in ("prompt", "completion")])
        ds[split] = ds[split].map(add_len, batched=True)

    # Filtrar (no truncar) lo que no cabe: truncar rompería el JSON de salida.
    def report_and_filter(split):
        before = len(ds[split])
        kept = ds[split].filter(lambda r: r["n_tokens"] <= args.max_seq_len)
        after = len(kept)
        lens = sorted(kept["n_tokens"]) or [0]
        p95 = lens[min(int(len(lens) * .95), len(lens) - 1)]
        print(f"[{split}] {after}/{before} ejemplos caben en {args.max_seq_len} tok "
              f"(descartados {before - after}); p50={lens[len(lens)//2]} p95={p95} "
              f"max={lens[-1]}")
        return kept

    train_ds = report_and_filter("train")
    eval_ds = report_and_filter("validation") if "validation" in ds else None
    if len(train_ds) == 0:
        raise SystemExit("0 ejemplos tras el filtro: sube --max-seq-len o reduce "
                         "el tamaño con build_sft_dataset.py --exp-voxel-cap.")

    # ---- Trainer -------------------------------------------------------------
    cfg = SFTConfig(
        dataset_text_field="text",
        max_seq_length=args.max_seq_len,
        dataset_num_proc=2,
        packing=False,                 # off: necesario para train_on_responses_only
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        warmup_ratio=args.warmup_ratio,
        num_train_epochs=args.epochs if args.max_steps <= 0 else 1,
        max_steps=args.max_steps if args.max_steps > 0 else -1,
        learning_rate=args.lr,
        logging_steps=1,
        optim="adamw_8bit",            # optimizador 8-bit: ahorra VRAM
        weight_decay=args.weight_decay,
        lr_scheduler_type="linear",
        seed=args.seed,
        output_dir=args.out,
        report_to="none",
        bf16=is_bfloat16_supported(),
        fp16=not is_bfloat16_supported(),
        save_strategy="no" if args.max_steps > 0 else "epoch",
        eval_strategy="steps" if (args.eval and eval_ds is not None) else "no",
        eval_steps=25 if args.eval else None,
        per_device_eval_batch_size=1,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=eval_ds if args.eval else None,
        args=cfg,
    )

    # Por defecto entrenamos sobre la secuencia completa (robusto ante cualquier
    # plantilla). --response-only enmascara el prompt, pero requiere que los
    # marcadores casen a nivel de tokens (frágil entre gemma4/qwen3_5).
    if args.response_only:
        if args.instruction_part and args.response_part:
            instr_part, resp_part = args.instruction_part, args.response_part
        else:
            det = detect_response_markers(tokenizer)
            instr_part, resp_part = det if det else response_markers(args.chat_template)
        print(f"[markers] response-only: instr={instr_part!r} resp={resp_part!r}")
        trainer = train_on_responses_only(
            trainer, instruction_part=instr_part, response_part=resp_part)
    else:
        print("[markers] entrenando sobre secuencia completa (prompt+completion)")

    # VRAM antes de entrenar
    gpu = torch.cuda.get_device_properties(0)
    print(f"GPU: {gpu.name}  VRAM total: {gpu.total_memory/1e9:.1f} GB  "
          f"reservada: {torch.cuda.max_memory_reserved()/1e9:.1f} GB")

    trainer.train()

    # ---- Guardado ------------------------------------------------------------
    adapter_dir = Path(args.out) / "lora_adapter"
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"Adapter LoRA guardado en {adapter_dir}")

    if args.merge:
        merged = Path(args.out) / "merged_16bit"
        model.save_pretrained_merged(str(merged), tokenizer, save_method="merged_16bit")
        print(f"Pesos 16-bit fusionados en {merged}")

    if args.save_gguf:
        model.save_pretrained_gguf(str(Path(args.out) / "gguf"), tokenizer,
                                   quantization_method=args.save_gguf)
        print(f"GGUF ({args.save_gguf}) exportado en {Path(args.out)/'gguf'}")


if __name__ == "__main__":
    main()
