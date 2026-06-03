#!/usr/bin/env python3
"""Prepare a full Qwen3.5-4B model directory with LM-MIDI tokenizer metadata.

This copies the base model directory, overlays the LM-MIDI tokenizer files,
and updates config vocab sizes so the training stack can resize/load against
the expanded vocabulary consistently.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


TOKENIZER_FILES = [
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
    "lm_midi_tokenizer_manifest.json",
]


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=False)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--lm-midi-tokenizer", type=Path, default=Path("Qwen3.5-4B-LM-MIDI"))
    parser.add_argument("--output-model", type=Path, default=Path("Qwen3.5-4B-LM-MIDI-Full"))
    args = parser.parse_args()

    if not args.base_model.exists():
        raise FileNotFoundError(args.base_model)
    if not args.lm_midi_tokenizer.exists():
        raise FileNotFoundError(args.lm_midi_tokenizer)

    copy_tree(args.base_model, args.output_model)

    for name in TOKENIZER_FILES:
        src = args.lm_midi_tokenizer / name
        if not src.exists():
            continue
        shutil.copy2(src, args.output_model / name)

    manifest = load_json(args.lm_midi_tokenizer / "lm_midi_tokenizer_manifest.json")
    vocab_size = int(manifest["vocab_size"])
    padded_vocab_size = ((vocab_size + 127) // 128) * 128

    config_path = args.output_model / "config.json"
    config = load_json(config_path)
    if "text_config" not in config:
        raise RuntimeError(f"{config_path} has no text_config")
    config["text_config"]["vocab_size"] = padded_vocab_size
    config["tie_word_embeddings"] = True
    config["text_config"]["tie_word_embeddings"] = True
    write_json(config_path, config)

    summary = {
        "base_model": str(args.base_model),
        "lm_midi_tokenizer": str(args.lm_midi_tokenizer),
        "output_model": str(args.output_model),
        "tokenizer_vocab_size": vocab_size,
        "model_vocab_size": padded_vocab_size,
    }
    write_json(args.output_model / "lm_midi_full_model_manifest.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
