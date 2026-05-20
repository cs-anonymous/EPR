#!/bin/bash
# Language CPT (Continual Pre-Training) with MS-SWIFT.
#
# Train Qwen3.5-4B LoRA on the language_cpt_s2 dataset from PianoCoReS/CoReS
# using DDP on 2 GPUs (0-1).

set -euo pipefail

MODEL_PATH="${MODEL_PATH:-./Qwen3.5-4B}"
TRAIN_DATA="${TRAIN_DATA:-./PianoCoReS/CoReS/language_cpt_s2_shuffled.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-./output/language-cpt}"

# GPU configuration for DDP on GPU 0-1
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1}"
NPROC_PER_NODE="${NPROC_PER_NODE:-2}"
MASTER_PORT="${MASTER_PORT:-29502}"

# Training hyperparameters
NUM_TRAIN_EPOCHS="${NUM_TRAIN_EPOCHS:-1}"
MAX_STEPS="${MAX_STEPS:-}"
PER_DEVICE_TRAIN_BATCH_SIZE="${PER_DEVICE_TRAIN_BATCH_SIZE:-2}"
GRADIENT_ACCUMULATION_STEPS="${GRADIENT_ACCUMULATION_STEPS:-4}"
LEARNING_RATE="${LEARNING_RATE:-1e-4}"
MAX_LENGTH="${MAX_LENGTH:-2048}"

# LoRA configuration
LORA_RANK="${LORA_RANK:-32}"
LORA_ALPHA="${LORA_ALPHA:-64}"
LORA_DROPOUT="${LORA_DROPOUT:-0.05}"
TARGET_MODULES="${TARGET_MODULES:-q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj}"
IFS=',' read -r -a TARGET_MODULES_ARGS <<< "$TARGET_MODULES"

# Logging and checkpointing
LOGGING_STEPS="${LOGGING_STEPS:-50}"
SAVE_STEPS="${SAVE_STEPS:-2000}"
SAVE_TOTAL_LIMIT="${SAVE_TOTAL_LIMIT:-3}"
DATALOADER_NUM_WORKERS="${DATALOADER_NUM_WORKERS:-4}"

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

swift pt \
    --model "$MODEL_PATH" \
    --dataset "$TRAIN_DATA" \
    --tuner_type lora \
    --torch_dtype bfloat16 \
    --num_train_epochs "$NUM_TRAIN_EPOCHS" \
    --per_device_train_batch_size "$PER_DEVICE_TRAIN_BATCH_SIZE" \
    --gradient_accumulation_steps "$GRADIENT_ACCUMULATION_STEPS" \
    --learning_rate "$LEARNING_RATE" \
    --lora_rank "$LORA_RANK" \
    --lora_alpha "$LORA_ALPHA" \
    --lora_dropout "$LORA_DROPOUT" \
    --target_modules "${TARGET_MODULES_ARGS[@]}" \
    --max_length "$MAX_LENGTH" \
    --logging_steps "$LOGGING_STEPS" \
    --save_steps "$SAVE_STEPS" \
    --save_total_limit "$SAVE_TOTAL_LIMIT" \
    --warmup_ratio 0.03 \
    --weight_decay 0.01 \
    --gradient_checkpointing true \
    --dataloader_num_workers "$DATALOADER_NUM_WORKERS" \
    --output_dir "$OUTPUT_DIR" \
    "${EXTRA_ARGS[@]}"
