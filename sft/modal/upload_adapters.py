"""Upload the local SFT LoRA adapters into the Modal volume `homecraft-adapters`.

The server (sft/modal/server.py) mounts this volume at /adapters and loads
/adapters/gemma-4-e2b and /adapters/gemma-4-e4b. Run once (re-run to update):

    python sft/modal/upload_adapters.py
"""
from __future__ import annotations
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "sft" / "outputs_vast"
ADAPTERS = {
    "gemma-4-e2b": SRC / "gemma-4-e2b" / "lora_adapter",
    "gemma-4-e4b": SRC / "gemma-4-e4b" / "lora_adapter",
}

vol = modal.Volume.from_name("homecraft-adapters", create_if_missing=True)


def main() -> int:
    missing = [k for k, p in ADAPTERS.items() if not (p / "adapter_config.json").exists()]
    if missing:
        raise SystemExit(f"missing local adapters: {missing}")
    with vol.batch_upload(force=True) as batch:
        for name, local in ADAPTERS.items():
            for f in sorted(local.iterdir()):
                if f.is_file():
                    batch.put_file(str(f), f"/{name}/{f.name}")
            print(f"[upload] {name}: {sum(1 for _ in local.iterdir())} files from {local}")
    print("[upload] committed to volume homecraft-adapters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
