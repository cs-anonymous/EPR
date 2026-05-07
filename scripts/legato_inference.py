#!/usr/bin/env python3
"""LEGATO inference with anti-loop generation params.

Usage:
    python scripts/legato_inference.py \
        --model_path legato/checkpoints/legato \
        --image_path <png-or-dir> \
        --output_path <out.json> [--beam_size 5] [--fp16]

Generation params (sweep-tested on D.960 pages 1-4):
  - num_beams=3             # stable coverage, avoids greedy's inconsistency
  - repetition_penalty=1.3  # essential: prevents [Aa]8- repeating-token collapse
  No ngram constraint needed — rep_penalty alone suffices.

Post-processing:
  - Strips `<|text|>` placeholder tokens (the model doesn't transcribe
    textual content; these are marker tokens for title/composer/nm=/"rit."
    annotations it chose to skip).

Output JSON:
  {
    "abc_transcription": [str, ...],            # one per input image, <|text|> stripped
    "abc_transcription_raw": [str, ...],        # unstripped, for debugging
    "image_files": [basename, ...]
  }
"""
import os, json, argparse, re
import torch
from PIL import Image
from legato.models import LegatoModel
from transformers import AutoProcessor, GenerationConfig


def strip_text_placeholders(abc: str) -> str:
    # "<|text|>" appears inside quoted strings, inside nm=<|text|>, or bare.
    # Remove entire annotations like `"<|text|>"` and strip inside nm=.../snm=...
    out = abc.replace('"<|text|>"', '')
    out = re.sub(r'"[\^_@<>][^"]*<\|text\|>[^"]*"', '', out)  # "^<|text|>" style
    out = re.sub(r'\b(nm|snm)=<\|text\|>\s*', '', out)
    out = out.replace('<|text|>', '')
    # Clean empty quoted annotations and trailing spaces left by removal
    out = re.sub(r'""', '', out)
    out = re.sub(r'[ \t]+\n', '\n', out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model_path", required=True)
    ap.add_argument("--processor_path", default=None)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--image_path", required=True, help="png/jpg file or directory of such")
    ap.add_argument("--output_path", required=True)
    ap.add_argument("--batch_size", type=int, default=1)
    ap.add_argument("--beam_size", type=int, default=3)
    ap.add_argument("--max_length", type=int, default=2048)
    ap.add_argument("--repetition_penalty", type=float, default=1.3)
    ap.add_argument("--fp16", action="store_true")
    args = ap.parse_args()

    args.processor_path = args.processor_path or args.model_path

    if os.path.isdir(args.image_path):
        files = sorted(
            f for f in os.listdir(args.image_path)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        )
        if not files:
            raise SystemExit(f"No png/jpg/jpeg in {args.image_path}")
        paths = [os.path.join(args.image_path, f) for f in files]
    else:
        paths = [args.image_path]
        files = [os.path.basename(args.image_path)]

    print(f"Loading model from {args.model_path} ...")
    model = LegatoModel.from_pretrained(args.model_path)
    processor = AutoProcessor.from_pretrained(args.processor_path)
    model = model.to(args.device)
    if args.fp16:
        model = model.half()

    gen_cfg = GenerationConfig(
        max_length=args.max_length,
        num_beams=args.beam_size,
        repetition_penalty=args.repetition_penalty,
    )

    raw_outputs, pretty_outputs = [], []
    for i in range(0, len(paths), args.batch_size):
        batch_paths = paths[i:i+args.batch_size]
        batch_imgs = [Image.open(p).convert("RGB") for p in batch_paths]
        inputs = processor(images=batch_imgs, truncation=True, return_tensors="pt")
        inputs = {k: v.to(args.device) for k, v in inputs.items()}
        with torch.no_grad():
            out_ids = model.generate(**inputs, generation_config=gen_cfg, use_model_defaults=False)
        decoded = processor.batch_decode(out_ids.tolist(), skip_special_tokens=True)
        for f, a in zip(batch_paths, decoded):
            print(f"  [{len(pretty_outputs)+1}/{len(paths)}] {os.path.basename(f)}: {len(a)} chars")
            raw_outputs.append(a)
            pretty_outputs.append(strip_text_placeholders(a))

    with open(args.output_path, "w") as f:
        json.dump({
            "abc_transcription": pretty_outputs,
            "abc_transcription_raw": raw_outputs,
            "image_files": files,
        }, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(pretty_outputs)} transcriptions to {args.output_path}")


if __name__ == "__main__":
    main()
