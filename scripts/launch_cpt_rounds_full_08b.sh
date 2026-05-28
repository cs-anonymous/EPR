#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"

ROUNDS_DIR="${ROUNDS_DIR:-${ROOT_DIR}/data/CorporaV2/language_cpt_rounds}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${ROOT_DIR}/output/cpt_qwen35_08b_full_rounds}"
BASE_MODEL="${BASE_MODEL:-${ROOT_DIR}/Qwen3.5-0.8B-LM-MIDI-Resized}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3}"
NPROC_PER_NODE="${NPROC_PER_NODE:-4}"
MASTER_PORT="${MASTER_PORT:-29531}"

NUM_TRAIN_EPOCHS="${NUM_TRAIN_EPOCHS:-1}"
PER_DEVICE_TRAIN_BATCH_SIZE="${PER_DEVICE_TRAIN_BATCH_SIZE:-1}"
GRADIENT_ACCUMULATION_STEPS="${GRADIENT_ACCUMULATION_STEPS:-8}"
LEARNING_RATE="${LEARNING_RATE:-5e-5}"
MAX_LENGTH="${MAX_LENGTH:-2048}"
LOGGING_STEPS="${LOGGING_STEPS:-20}"
SAVE_STEPS="${SAVE_STEPS:-500}"
SAVE_TOTAL_LIMIT="${SAVE_TOTAL_LIMIT:-3}"
DATALOADER_NUM_WORKERS="${DATALOADER_NUM_WORKERS:-2}"

export CUDA_VISIBLE_DEVICES
export NPROC_PER_NODE
export MASTER_PORT
export MKL_SERVICE_FORCE_INTEL="${MKL_SERVICE_FORCE_INTEL:-1}"
export MKL_THREADING_LAYER="${MKL_THREADING_LAYER:-GNU}"

latest_checkpoint_dir() {
  local out_dir="$1"
  if [[ -d "${out_dir}/final_model" ]]; then
    printf '%s\n' "${out_dir}/final_model"
    return
  fi
  local latest
  latest="$(find "${out_dir}" -type d -name 'checkpoint-*' | sort -V | tail -n 1 || true)"
  if [[ -n "${latest}" ]]; then
    printf '%s\n' "${latest}"
    return
  fi
  printf '%s\n' "${out_dir}"
}

latest_resume_checkpoint() {
  local out_dir="$1"
  find "${out_dir}" -type d -name 'checkpoint-*' | sort -V | tail -n 1 || true
}

run_round() {
  local round_name="$1"
  local model_path="$2"
  local dataset_path="${ROUNDS_DIR}/${round_name}_train.jsonl"
  local output_dir="${OUTPUT_ROOT}/${round_name}"
  local resume_ckpt=""

  if [[ ! -f "${dataset_path}" ]]; then
    echo "Missing dataset: ${dataset_path}" >&2
    exit 1
  fi

  if [[ -d "${output_dir}/final_model" ]]; then
    echo "=== ${round_name} already finished, skipping ==="
    return 0
  fi

  mkdir -p "${output_dir}"
  resume_ckpt="$(latest_resume_checkpoint "${output_dir}")"
  echo "=== ${round_name} ==="
  echo "model: ${model_path}"
  echo "dataset: ${dataset_path}"
  echo "output: ${output_dir}"
  if [[ -n "${resume_ckpt}" ]]; then
    echo "resume_from_checkpoint: ${resume_ckpt}"
  fi

  local cmd=(
    torchrun
    --nproc_per_node "${NPROC_PER_NODE}" \
    --master_port "${MASTER_PORT}" \
    "${ROOT_DIR}/scripts/train_cpt_hf_full.py" \
    --model "${model_path}" \
    --dataset "${dataset_path}" \
    --output-dir "${output_dir}" \
    --num-train-epochs "${NUM_TRAIN_EPOCHS}" \
    --per-device-train-batch-size "${PER_DEVICE_TRAIN_BATCH_SIZE}" \
    --gradient-accumulation-steps "${GRADIENT_ACCUMULATION_STEPS}" \
    --learning-rate "${LEARNING_RATE}" \
    --max-length "${MAX_LENGTH}" \
    --logging-steps "${LOGGING_STEPS}" \
    --save-steps "${SAVE_STEPS}" \
    --save-total-limit "${SAVE_TOTAL_LIMIT}" \
    --dataloader-num-workers "${DATALOADER_NUM_WORKERS}"
  )
  if [[ -n "${resume_ckpt}" ]]; then
    cmd+=(--resume-from-checkpoint "${resume_ckpt}")
  fi
  "${cmd[@]}"
}

main() {
  mkdir -p "${OUTPUT_ROOT}"

  local current_model="${BASE_MODEL}"
  for round_name in round1 round2 round3 round4 round5; do
    if [[ -d "${OUTPUT_ROOT}/${round_name}/final_model" ]]; then
      echo "=== ${round_name} already finished, using final_model ==="
    else
      run_round "${round_name}" "${current_model}"
    fi
    current_model="$(latest_checkpoint_dir "${OUTPUT_ROOT}/${round_name}")"
    echo "next model: ${current_model}"
  done
}

main "$@"
