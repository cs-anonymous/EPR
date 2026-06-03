#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"
export PYTHONPATH

PROXY_URL="${PROXY_URL:-}"
if [[ -n "${PROXY_URL}" ]]; then
  export http_proxy="${PROXY_URL}"
  export https_proxy="${PROXY_URL}"
fi

WGET_PROXY_ARGS=()
if [[ -n "${PROXY_URL}" ]]; then
  WGET_PROXY_ARGS=(-e use_proxy=yes -e "https_proxy=${PROXY_URL}")
fi

usage() {
  cat <<'EOF'
Usage:
  scripts/prepare_qwen35_lm_midi_variants.sh MODEL_NAME [MODEL_NAME ...]

Example:
  PROXY_URL=http://127.0.0.1:7890 \
    scripts/prepare_qwen35_lm_midi_variants.sh Qwen3.5-0.8B Qwen3.5-2B
EOF
}

download_model_file() {
  local model_name="$1"
  local file_name="$2"
  local output_path="${ROOT_DIR}/${model_name}/${file_name}"
  mkdir -p "$(dirname "${output_path}")"
  wget -c "${WGET_PROXY_ARGS[@]}" -O "${output_path}" \
    "https://huggingface.co/Qwen/${model_name}/resolve/main/${file_name}"
}

download_model_dir() {
  local model_name="$1"
  local output_dir="${ROOT_DIR}/${model_name}"
  mkdir -p "${output_dir}"

  local small_files=(
    .gitattributes
    LICENSE
    README.md
    chat_template.jinja
    config.json
    merges.txt
    model.safetensors.index.json
    preprocessor_config.json
    tokenizer.json
    tokenizer_config.json
    video_preprocessor_config.json
    vocab.json
  )

  for file_name in "${small_files[@]}"; do
    if [[ ! -f "${output_dir}/${file_name}" ]]; then
      download_model_file "${model_name}" "${file_name}"
    fi
  done

  local weight_file
  weight_file="$(
    python - "${output_dir}/model.safetensors.index.json" <<'PY'
import json
import sys
from pathlib import Path

index_path = Path(sys.argv[1])
data = json.loads(index_path.read_text(encoding="utf-8"))
files = sorted(set(data["weight_map"].values()))
if len(files) != 1:
    raise SystemExit(f"expected exactly one weight file, got: {files}")
print(files[0])
PY
  )"
  download_model_file "${model_name}" "${weight_file}"
}

prepare_variant() {
  local model_name="$1"
  local base_dir="${ROOT_DIR}/${model_name}"
  local tokenizer_dir="${ROOT_DIR}/${model_name}-LM-MIDI"
  local resized_dir="${ROOT_DIR}/${model_name}-LM-MIDI-Resized"

  download_model_dir "${model_name}"

  python "${ROOT_DIR}/scripts/extend_lm_midi_tokenizer.py" \
    --base-tokenizer "${base_dir}" \
    --out-tokenizer "${tokenizer_dir}" \
    --mode full \
    --overwrite

  python "${ROOT_DIR}/scripts/resize_qwen35_lm_midi_embeddings.py" \
    --base-model "${base_dir}" \
    --expanded-tokenizer "${tokenizer_dir}" \
    --output-model "${resized_dir}" \
    --dtype bfloat16
}

main() {
  if [[ "$#" -lt 1 ]]; then
    usage
    exit 1
  fi

  for model_name in "$@"; do
    echo "=== Preparing ${model_name} ==="
    prepare_variant "${model_name}"
  done
}

main "$@"
