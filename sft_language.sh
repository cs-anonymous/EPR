#!/bin/bash
# Language SFT training with MS-SWIFT.
#
# Defaults train Qwen3.5-4B LoRA on the merged score/performance language
# dataset produced by prepare_sft_data.py:
#   sft_data/core-s1/sft_language_train.jsonl
#   sft_data/core-s1-val/sft_language_val.jsonl

set -euo pipefail

MODEL_PATH="${MODEL_PATH:-./Qwen3.5-4B}"
DEFAULT_TRAIN_DATA="./sft_data/core-s1/sft_language_train_le512.jsonl"
DEFAULT_VAL_DATA="./sft_data/core-s1-val/sft_language_val_20k_le512.jsonl"
[[ -f "$DEFAULT_TRAIN_DATA" ]] || DEFAULT_TRAIN_DATA="./sft_data/core-s1/sft_language_train.jsonl"
[[ -f "$DEFAULT_VAL_DATA" ]] || DEFAULT_VAL_DATA="./sft_data/core-s1-val/sft_language_val_20k.jsonl"

TRAIN_DATA="${TRAIN_DATA:-$DEFAULT_TRAIN_DATA}"
VAL_DATA="${VAL_DATA:-$DEFAULT_VAL_DATA}"
OUTPUT_DIR="${OUTPUT_DIR:-./output/language-sft}"

CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-2,3}"
NPROC_PER_NODE="${NPROC_PER_NODE:-4}"
MASTER_PORT="${MASTER_PORT:-29501}"

NUM_TRAIN_EPOCHS="${NUM_TRAIN_EPOCHS:-1}"
MAX_STEPS="${MAX_STEPS:-}"
PER_DEVICE_TRAIN_BATCH_SIZE="${PER_DEVICE_TRAIN_BATCH_SIZE:-8}"
PER_DEVICE_EVAL_BATCH_SIZE="${PER_DEVICE_EVAL_BATCH_SIZE:-8}"
GRADIENT_ACCUMULATION_STEPS="${GRADIENT_ACCUMULATION_STEPS:-2}"
LEARNING_RATE="${LEARNING_RATE:-2e-4}"
MAX_LENGTH="${MAX_LENGTH:-512}"
LORA_RANK="${LORA_RANK:-32}"
LORA_ALPHA="${LORA_ALPHA:-64}"
LORA_DROPOUT="${LORA_DROPOUT:-0.1}"
LOGGING_STEPS="${LOGGING_STEPS:-50}"
EVAL_STEPS="${EVAL_STEPS:-2000}"
SAVE_STEPS="${SAVE_STEPS:-2000}"
SAVE_TOTAL_LIMIT="${SAVE_TOTAL_LIMIT:-3}"
DATALOADER_NUM_WORKERS="${DATALOADER_NUM_WORKERS:-2}"
ADD_VERSION="${ADD_VERSION:-true}"
TRUNCATION_STRATEGY="${TRUNCATION_STRATEGY:-delete}"
RESUME_FROM_CHECKPOINT="${RESUME_FROM_CHECKPOINT:-}"

export MKL_SERVICE_FORCE_INTEL="${MKL_SERVICE_FORCE_INTEL:-1}"
export CUDA_VISIBLE_DEVICES
export NPROC_PER_NODE
export MASTER_PORT

EXTRA_ARGS=()
if [[ -n "$RESUME_FROM_CHECKPOINT" ]]; then
    EXTRA_ARGS+=(--resume_from_checkpoint "$RESUME_FROM_CHECKPOINT")
fi
if [[ -n "$MAX_STEPS" ]]; then
    EXTRA_ARGS+=(--max_steps "$MAX_STEPS")
fi

swift sft \
    --model "$MODEL_PATH" \
    --dataset "$TRAIN_DATA" \
    --val_dataset "$VAL_DATA" \
    --tuner_type lora \
    --torch_dtype bfloat16 \
    --num_train_epochs "$NUM_TRAIN_EPOCHS" \
    --per_device_train_batch_size "$PER_DEVICE_TRAIN_BATCH_SIZE" \
    --per_device_eval_batch_size "$PER_DEVICE_EVAL_BATCH_SIZE" \
    --gradient_accumulation_steps "$GRADIENT_ACCUMULATION_STEPS" \
    --learning_rate "$LEARNING_RATE" \
    --lora_rank "$LORA_RANK" \
    --lora_alpha "$LORA_ALPHA" \
    --lora_dropout "$LORA_DROPOUT" \
    --target_modules all-linear \
    --max_length "$MAX_LENGTH" \
    --truncation_strategy "$TRUNCATION_STRATEGY" \
    --logging_steps "$LOGGING_STEPS" \
    --eval_steps "$EVAL_STEPS" \
    --save_steps "$SAVE_STEPS" \
    --save_total_limit "$SAVE_TOTAL_LIMIT" \
    --warmup_ratio 0.05 \
    --weight_decay 0.01 \
    --gradient_checkpointing true \
    --dataloader_num_workers "$DATALOADER_NUM_WORKERS" \
    --add_version "$ADD_VERSION" \
    --output_dir "$OUTPUT_DIR" \
    "${EXTRA_ARGS[@]}"
