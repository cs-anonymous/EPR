#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"

ROUNDS_DIR="${ROUNDS_DIR:-${ROOT_DIR}/data/CorporaV2/language_cpt/rounds}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${ROOT_DIR}/output/cpt_qwen35_4b_lora_rounds_$(date +%Y%m%d_%H%M%S)}"
BASE_MODEL="${BASE_MODEL:-${ROOT_DIR}/Qwen3.5-4B-LM-MIDI-Resized}"
BASE_TOKENIZER="${BASE_TOKENIZER:-${ROOT_DIR}/Qwen3.5-4B}"
EXPANDED_TOKENIZER="${EXPANDED_TOKENIZER:-${ROOT_DIR}/Qwen3.5-4B-LM-MIDI}"

# GPU 1-3, 3 GPUs
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1,2,3}"
NPROC_PER_NODE="${NPROC_PER_NODE:-3}"
MASTER_PORT="${MASTER_PORT:-29541}"

NUM_TRAIN_EPOCHS="${NUM_TRAIN_EPOCHS:-1}"
PER_DEVICE_TRAIN_BATCH_SIZE="${PER_DEVICE_TRAIN_BATCH_SIZE:-2}"
GRADIENT_ACCUMULATION_STEPS="${GRADIENT_ACCUMULATION_STEPS:-4}"
LEARNING_RATE="${LEARNING_RATE:-1e-4}"
MAX_LENGTH="${MAX_LENGTH:-2048}"
LOGGING_STEPS="${LOGGING_STEPS:-20}"
SAVE_STEPS="${SAVE_STEPS:-500}"
SAVE_TOTAL_LIMIT="${SAVE_TOTAL_LIMIT:-3}"
DATALOADER_NUM_WORKERS="${DATALOADER_NUM_WORKERS:-4}"

# LoRA configuration
LORA_RANK="${LORA_RANK:-32}"
LORA_ALPHA="${LORA_ALPHA:-64}"
LORA_DROPOUT="${LORA_DROPOUT:-0.05}"
TARGET_MODULES="${TARGET_MODULES:-q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj}"

export CUDA_VISIBLE_DEVICES
export NPROC_PER_NODE
export MASTER_PORT
export MKL_SERVICE_FORCE_INTEL="${MKL_SERVICE_FORCE_INTEL:-1}"
export MKL_THREADING_LAYER="${MKL_THREADING_LAYER:-GNU}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

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
  local dataset_path="${ROUNDS_DIR}/${round_name}.jsonl"
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
  echo "GPUs: ${CUDA_VISIBLE_DEVICES}"
  echo "LoRA rank: ${LORA_RANK}"
  if [[ -n "${resume_ckpt}" ]]; then
    echo "resume_from_checkpoint: ${resume_ckpt}"
  fi

  local cmd=(
    torchrun
    --nproc_per_node "${NPROC_PER_NODE}"
    --master_port "${MASTER_PORT}"
    "${ROOT_DIR}/scripts/training/train_cpt_hf_peft.py"
    --model "${model_path}"
    --dataset "${dataset_path}"
    --output-dir "${output_dir}"
    --base-tokenizer "${BASE_TOKENIZER}"
    --expanded-tokenizer "${EXPANDED_TOKENIZER}"
    --num-train-epochs "${NUM_TRAIN_EPOCHS}"
    --per-device-train-batch-size "${PER_DEVICE_TRAIN_BATCH_SIZE}"
    --gradient-accumulation-steps "${GRADIENT_ACCUMULATION_STEPS}"
    --learning-rate "${LEARNING_RATE}"
    --max-length "${MAX_LENGTH}"
    --logging-steps "${LOGGING_STEPS}"
    --save-steps "${SAVE_STEPS}"
    --save-total-limit "${SAVE_TOTAL_LIMIT}"
    --dataloader-num-workers "${DATALOADER_NUM_WORKERS}"
    --lora-rank "${LORA_RANK}"
    --lora-alpha "${LORA_ALPHA}"
    --lora-dropout "${LORA_DROPOUT}"
    --target-modules "${TARGET_MODULES}"
    --bf16
    --gradient-checkpointing
  )
  if [[ -n "${resume_ckpt}" ]]; then
    cmd+=(--resume-from-checkpoint "${resume_ckpt}")
  fi

  "${cmd[@]}" 2>&1 | tee "${output_dir}/train.log"
}

main() {
  mkdir -p "${OUTPUT_ROOT}"

  echo "========================================"
  echo "CPT 4B LoRA Training - Rounds"
  echo "========================================"
  echo "Base model: ${BASE_MODEL}"
  echo "Output root: ${OUTPUT_ROOT}"
  echo "Rounds dir: ${ROUNDS_DIR}"
  echo "GPUs: ${CUDA_VISIBLE_DEVICES} (${NPROC_PER_NODE} processes)"
  echo "LoRA rank: ${LORA_RANK}"
  echo "========================================"

  local current_model="${BASE_MODEL}"
  for round_name in train_S1 train_S2 train_Astar1 train_Astar2 train_Astar3; do
    if [[ -d "${OUTPUT_ROOT}/${round_name}/final_model" ]]; then
      echo "=== ${round_name} already finished, using final_model ==="
    else
      run_round "${round_name}" "${current_model}"
    fi
    current_model="$(latest_checkpoint_dir "${OUTPUT_ROOT}/${round_name}")"
    echo "next model: ${current_model}"
  done

  echo "========================================"
  echo "All rounds completed!"
  echo "Final model: ${current_model}"
  echo "========================================"
}

main "$@"
