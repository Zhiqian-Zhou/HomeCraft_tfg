"""Utilidades compartidas entre entrenamiento e inferencia del SFT.

Mantener el MISMO prompt-wrapper en train e inferencia es crítico: el modelo
solo generaliza si en inferencia ve exactamente el mismo formato con el que
fue entrenado.
"""
from __future__ import annotations

# Instrucción fija que envuelve la descripción del usuario. Corta a propósito
# (cada token cuenta porque las salidas ya son largas).
SYSTEM_INSTRUCTION = (
    "You are an architect that designs Minecraft Java 1.16.5 buildings as voxel "
    "JSON. Given a description, output ONLY a JSON object with keys "
    "block_palette, voxels ([[x,y,z,palette_idx],...]), bounding_box and tags. "
    "No air blocks, no prose."
)


def build_user_turn(description: str) -> str:
    """Contenido del turno 'user' (Gemma no tiene rol system propio)."""
    return f"{SYSTEM_INSTRUCTION}\n\nDescription:\n{description.strip()}"


def build_messages(description: str, completion: str | None = None) -> list[dict]:
    """Conversación en formato chat. Si `completion` es None → para inferencia."""
    msgs = [{"role": "user", "content": build_user_turn(description)}]
    if completion is not None:
        msgs.append({"role": "assistant", "content": completion})
    return msgs


# Marcadores de cada chat-template, usados por train_on_responses_only para
# enmascarar el prompt y entrenar SOLO sobre la respuesta (el JSON).
# clave = nombre de plantilla de unsloth get_chat_template.
RESPONSE_MARKERS = {
    "gemma2":  ("<start_of_turn>user\n", "<start_of_turn>model\n"),
    "gemma-3": ("<start_of_turn>user\n", "<start_of_turn>model\n"),
    "qwen-2.5": ("<|im_start|>user\n", "<|im_start|>assistant\n"),
    "qwen3":    ("<|im_start|>user\n", "<|im_start|>assistant\n"),
    "chatml":   ("<|im_start|>user\n", "<|im_start|>assistant\n"),
}

# Compatibilidad hacia atrás.
GEMMA_INSTRUCTION_PART, GEMMA_RESPONSE_PART = RESPONSE_MARKERS["gemma2"]


def response_markers(chat_template: str) -> tuple[str, str]:
    """(instruction_part, response_part) para la plantilla dada."""
    if chat_template not in RESPONSE_MARKERS:
        raise KeyError(
            f"plantilla '{chat_template}' sin marcadores; añádela a RESPONSE_MARKERS "
            f"o pasa --instruction-part/--response-part. Conocidas: "
            f"{sorted(RESPONSE_MARKERS)}")
    return RESPONSE_MARKERS[chat_template]


def detect_response_markers(tokenizer):
    """Deriva (instruction_part, response_part) de la PROPIA plantilla del modelo.

    Robusto ante plantillas nuevas (gemma4 usa '<|turn>model\\n', qwen usa
    '<|im_start|>assistant\\n', etc.). Devuelve None si no se puede inferir.
    """
    U = "☃USER_SENTINEL☃"
    A = "☃ASST_SENTINEL☃"
    try:
        s = tokenizer.apply_chat_template(
            [{"role": "user", "content": U}, {"role": "assistant", "content": A}],
            tokenize=False, add_generation_prompt=False)
    except Exception:
        return None
    if U not in s or A not in s:
        return None
    instr = s.split(U, 1)[0]              # p.ej. "<bos><|turn>user\n"
    resp = s.split(U, 1)[1].split(A, 1)[0]  # p.ej. "<turn|>\n<|turn>model\n"
    if not instr or not resp:
        return None
    return instr, resp
