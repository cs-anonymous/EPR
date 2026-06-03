#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"

ROUNDS_DIR="${ROUNDS_DIR:-${ROOT_DIR}/data/CorporaV2/language_cpt/rounds}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${ROOT_DIR}/output/cpt_qwen35_08b_full_rounds_continuous_3gpu_123_$(date +%Y%m%d_%H%M%S)}"
BASE_MODEL="${BASE_MODEL:-${ROOT_DIR}/Qwen3.5-0.8B-LM-MIDI-Resized}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1,2,3}"
NPROC_PER_NODE="${NPROC_PER_NODE:-3}"
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

mkdir -p "${OUTPUT_ROOT}"

torchrun \
  --nproc_per_node "${NPROC_PER_NODE}" \
  --master_port "${MASTER_PORT}" \
  "${ROOT_DIR}/scripts/train_cpt_hf_full_continuous_rounds.py" \
  --model "${BASE_MODEL}" \
  --rounds-dir "${ROUNDS_DIR}" \
  --rounds train_S1 train_S2 train_Astar1 train_Astar2 train_Astar3 \
  --output-dir "${OUTPUT_ROOT}" \
  --num-train-epochs "${NUM_TRAIN_EPOCHS}" \
  --per-device-train-batch-size "${PER_DEVICE_TRAIN_BATCH_SIZE}" \
  --gradient-accumulation-steps "${GRADIENT_ACCUMULATION_STEPS}" \
  --learning-rate "${LEARNING_RATE}" \
  --max-length "${MAX_LENGTH}" \
  --logging-steps "${LOGGING_STEPS}" \
  --save-steps "${SAVE_STEPS}" \
  --save-total-limit "${SAVE_TOTAL_LIMIT}" \
  --dataloader-num-workers "${DATALOADER_NUM_WORKERS}"
