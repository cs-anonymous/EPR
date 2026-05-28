#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODEL="${MODEL:-./Qwen3.5-4B-LM-MIDI-Resized}"
ADAPTER="${ADAPTER:-./output/abcx2pm-s1-sft-from-cpt-r32-hf-1536/v3-20260524-003023/checkpoint-13138}"
CHECKPOINT_NAME="${CHECKPOINT_NAME:-language_cpt_s1_abcx2pm_sft_s1}"
OUTPUT_DIR="${OUTPUT_DIR:-./output/${CHECKPOINT_NAME}}"
TMP_DIR="${TMP_DIR:-${OUTPUT_DIR}.tmp-merge}"
RUN_SMOKE="${RUN_SMOKE:-1}"
SMOKE_INPUT="${SMOKE_INPUT:-./backup/legacy_Corpora/abcx2pm_sft/abcx2pm_coldstart_test.jsonl}"
SMOKE_COUNT="${SMOKE_COUNT:-1}"
SMOKE_OUT_DIR="${SMOKE_OUT_DIR:-${OUTPUT_DIR}/smoke}"
SMOKE_MAX_TOKENS="${SMOKE_MAX_TOKENS:-128}"
SMOKE_TP_SIZE="${SMOKE_TP_SIZE:-1}"
SMOKE_GPU_UTIL="${SMOKE_GPU_UTIL:-0.80}"
VLLM_CONDA_ENV="${VLLM_CONDA_ENV:-vllm-swift}"
CONDA_BIN="${CONDA_BIN:-$(command -v conda || true)}"

require_path() {
    local path="$1"
    if [[ ! -e "$path" ]]; then
        echo "Missing required path: $path" >&2
        exit 1
    fi
}

run_vllm_python() {
    if [[ -n "$VLLM_CONDA_ENV" ]]; then
        if [[ -z "$CONDA_BIN" ]]; then
            echo "conda not found, but VLLM_CONDA_ENV=$VLLM_CONDA_ENV was requested" >&2
            exit 1
        fi
        "$CONDA_BIN" run -n "$VLLM_CONDA_ENV" python "$@"
    else
        python "$@"
    fi
}

require_path "$MODEL/config.json"
require_path "$MODEL/tokenizer.json"
require_path "$ADAPTER/adapter_config.json"
require_path "$ADAPTER/adapter_model.safetensors"

if [[ -e "$OUTPUT_DIR" ]]; then
    echo "Refusing to overwrite existing output dir: $OUTPUT_DIR" >&2
    echo "Remove it manually or pass a different OUTPUT_DIR." >&2
    exit 1
fi

rm -rf "$TMP_DIR"

export MKL_SERVICE_FORCE_INTEL="${MKL_SERVICE_FORCE_INTEL:-1}"

swift export \
  --model "$MODEL" \
  --adapters "$ADAPTER" \
  --torch_dtype bfloat16 \
  --merge_lora true \
  --device_map cpu \
  --safe_serialization true \
  --output_dir "$TMP_DIR" \
  --exist_ok true

python - "$TMP_DIR" "$OUTPUT_DIR" <<'PY'
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from safetensors import safe_open
from safetensors.torch import save_file

OLD_PREFIX = "model.language_model."
NEW_PREFIX = "model."


def remap_key(key: str) -> str:
    if key.startswith(OLD_PREFIX):
        return NEW_PREFIX + key[len(OLD_PREFIX) :]
    return key


def rewrite_index(src_dir: Path, dst_dir: Path) -> None:
    index_path = src_dir / "model.safetensors.index.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    weight_map = data["weight_map"]
    data["weight_map"] = {remap_key(key): shard for key, shard in weight_map.items()}
    (dst_dir / index_path.name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def rewrite_shard(src_path: Path, dst_path: Path) -> None:
    tensors = {}
    metadata = None
    with safe_open(src_path, framework="pt", device="cpu") as f:
        metadata = f.metadata()
        for key in f.keys():
            tensors[remap_key(key)] = f.get_tensor(key)
    save_file(tensors, str(dst_path), metadata=metadata)


def main() -> None:
    src_dir = Path(sys.argv[1]).resolve()
    dst_dir = Path(sys.argv[2]).resolve()
    dst_dir.mkdir(parents=True, exist_ok=False)

    shard_paths = sorted(src_dir.glob("model-*.safetensors"))
    if not shard_paths:
        raise FileNotFoundError(f"No model shards found under {src_dir}")

    for path in src_dir.iterdir():
        if path.name == "model.safetensors.index.json":
            continue
        if path.name.startswith("model-") and path.suffix == ".safetensors":
            continue
        if path.is_file():
            shutil.copy2(path, dst_dir / path.name)

    rewrite_index(src_dir, dst_dir)
    for shard_path in shard_paths:
        rewrite_shard(shard_path, dst_dir / shard_path.name)


if __name__ == "__main__":
    main()
PY

rm -rf "$TMP_DIR"

echo "Exported vLLM checkpoint to: $OUTPUT_DIR"

if [[ "$RUN_SMOKE" == "1" ]]; then
    require_path "$SMOKE_INPUT"
    mkdir -p "$SMOKE_OUT_DIR"

    python backup/scripts_legacy/eval_abcx2pm_test.py prepare \
      --input "$SMOKE_INPUT" \
      --out-dir "$SMOKE_OUT_DIR" \
      --count "$SMOKE_COUNT" \
      --distinct-works

    run_vllm_python backup/scripts_legacy/vllm_abcx2pm_smoke.py \
      --model "$OUTPUT_DIR" \
      --input "$SMOKE_OUT_DIR/infer_messages.jsonl" \
      --output "$SMOKE_OUT_DIR/results.jsonl" \
      --tensor-parallel-size "$SMOKE_TP_SIZE" \
      --gpu-memory-utilization "$SMOKE_GPU_UTIL" \
      --max-model-len 1536 \
      --max-tokens "$SMOKE_MAX_TOKENS" \
      --enforce-eager \
      --limit "$SMOKE_COUNT"

    python backup/scripts_legacy/eval_abcx2pm_test.py postprocess \
      --manifest "$SMOKE_OUT_DIR/manifest.jsonl" \
      --results "$SMOKE_OUT_DIR/results.jsonl" \
      --out-dir "$SMOKE_OUT_DIR/decoded"

    echo "Smoke outputs written to: $SMOKE_OUT_DIR"
fi
