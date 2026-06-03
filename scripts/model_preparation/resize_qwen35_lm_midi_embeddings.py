#!/usr/bin/env python3
"""Create a fully resized Qwen3.5-4B LM-MIDI model checkpoint.

This loads the base model weights, resizes token embeddings to match the
expanded LM-MIDI tokenizer, and saves a new full checkpoint so downstream
training does not rely on shape-mismatch loading.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import torch
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer


TOKENIZER_FILES = [
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
    "lm_midi_tokenizer_manifest.json",
    "merges.txt",
    "vocab.json",
]


def copy_extra_files(base_model: Path, tokenizer_dir: Path, output_dir: Path) -> None:
    for name in ["LICENSE", "README.md", "configuration.json", "preprocessor_config.json", "video_preprocessor_config.json"]:
        src = base_model / name
        if src.exists():
            shutil.copy2(src, output_dir / name)
    for name in TOKENIZER_FILES:
        src = tokenizer_dir / name
        if src.exists():
            shutil.copy2(src, output_dir / name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--expanded-tokenizer", type=Path, default=Path("Qwen3.5-4B-LM-MIDI"))
    parser.add_argument("--output-model", type=Path, default=Path("Qwen3.5-4B-LM-MIDI-Resized"))
    parser.add_argument("--dtype", type=str, default="bfloat16")
    args = parser.parse_args()

    if args.output_model.exists():
        shutil.rmtree(args.output_model)
    args.output_model.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(str(args.expanded_tokenizer), trust_remote_code=True)
    config = AutoConfig.from_pretrained(str(args.base_model), trust_remote_code=True)
    target_vocab_size = ((len(tokenizer) + 127) // 128) * 128
    config.text_config.vocab_size = target_vocab_size
    config.tie_word_embeddings = True
    if hasattr(config, "tie_word_embeddings"):
        config.tie_word_embeddings = True

    torch_dtype = getattr(torch, args.dtype)
    model = AutoModelForCausalLM.from_pretrained(
        str(args.base_model),
        trust_remote_code=True,
        config=config,
        torch_dtype=torch_dtype,
        ignore_mismatched_sizes=True,
    )
    model.resize_token_embeddings(target_vocab_size)

    model.save_pretrained(str(args.output_model), safe_serialization=True, max_shard_size="5GB")
    tokenizer.save_pretrained(str(args.output_model))
    copy_extra_files(args.base_model, args.expanded_tokenizer, args.output_model)

    manifest = {
        "base_model": str(args.base_model),
        "expanded_tokenizer": str(args.expanded_tokenizer),
        "output_model": str(args.output_model),
        "tokenizer_vocab_size": len(tokenizer),
        "saved_vocab_size": target_vocab_size,
        "dtype": args.dtype,
    }
    (args.output_model / "lm_midi_resized_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
