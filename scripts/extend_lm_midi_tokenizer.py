#!/usr/bin/env python3
"""Create a tokenizer copy with LM-MIDI tokens added as indivisible tokens."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from transformers import AddedToken, AutoTokenizer


def lm_midi_tokens() -> list[str]:
    tokens: list[str] = []
    tokens += [f"<N{i:03d}>" for i in range(128)]
    tokens += [f"<V{i:03d}>" for i in range(128)]
    tokens += [f"<T{i:03d}>" for i in range(256)]
    tokens += [
        "<MIDI>",
        "</MIDI>",
        "<EOS_MIDI>",
        "<NIL>",
        "<EXT>",
        "<EXD>",
        "<EXO>",
        "<M>",
        "<H>",
        "<P>",
        "<P1>",
        "<P2>",
    ]
    return tokens


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--out-tokenizer", type=Path, default=Path("Qwen3.5-4B-LM-MIDI"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.out_tokenizer.exists():
        if not args.overwrite:
            raise FileExistsError(f"{args.out_tokenizer} already exists; pass --overwrite")
        shutil.rmtree(args.out_tokenizer)

    tokenizer = AutoTokenizer.from_pretrained(str(args.base_tokenizer), trust_remote_code=True)
    added_tokens = [
        AddedToken(token, single_word=False, lstrip=False, rstrip=False, normalized=False)
        for token in lm_midi_tokens()
    ]
    added = tokenizer.add_tokens(added_tokens)
    args.out_tokenizer.mkdir(parents=True)
    tokenizer.save_pretrained(str(args.out_tokenizer))

    manifest = {
        "base_tokenizer": str(args.base_tokenizer),
        "added_tokens": added,
        "total_lm_midi_tokens": len(added_tokens),
        "vocab_size": len(tokenizer),
    }
    (args.out_tokenizer / "lm_midi_tokenizer_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    ids = tokenizer.encode("<N060><V072><T048><T000>", add_special_tokens=False)
    if len(ids) != 4:
        raise RuntimeError(f"LM-MIDI token verification failed: expected 4 tokens, got {len(ids)}")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
