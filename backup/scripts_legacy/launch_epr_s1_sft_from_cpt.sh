#!/usr/bin/env bash
# Launch abcx2pm_s1 and sm2pm_s1 SFT from the finished CPT LoRA adapter.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TS="$(date +%Y%m%d_%H%M%S)"
MODEL="${MODEL:-./Qwen3.5-4B-LM-MIDI-Resized}"
CPT_ADAPTER="${CPT_ADAPTER:-./output/language-cpt-s1-r32-hf-1536/checkpoint-14982}"

NUM_TRAIN_EPOCHS="${NUM_TRAIN_EPOCHS:-1}"
PER_DEVICE_TRAIN_BATCH_SIZE="${PER_DEVICE_TRAIN_BATCH_SIZE:-2}"
PER_DEVICE_EVAL_BATCH_SIZE="${PER_DEVICE_EVAL_BATCH_SIZE:-1}"
GRADIENT_ACCUMULATION_STEPS="${GRADIENT_ACCUMULATION_STEPS:-8}"
LEARNING_RATE="${LEARNING_RATE:-1e-4}"
MAX_LENGTH="${MAX_LENGTH:-1536}"
LOGGING_STEPS="${LOGGING_STEPS:-50}"
EVAL_STEPS="${EVAL_STEPS:-2000}"
SAVE_STEPS="${SAVE_STEPS:-2000}"
SAVE_TOTAL_LIMIT="${SAVE_TOTAL_LIMIT:-3}"
DATASET_NUM_PROC="${DATASET_NUM_PROC:-8}"
DATALOADER_NUM_WORKERS="${DATALOADER_NUM_WORKERS:-2}"

require_path() {
    local path="$1"
    if [[ ! -e "$path" ]]; then
        echo "Missing required path: $path" >&2
        exit 1
    fi
}

launch_task() {
    local task="$1"
    local gpus="$2"
    local port="$3"
    local train_data="$4"
    local val_data="$5"
    local output_dir="$6"
    local log_path="$7"

    require_path "$train_data"
    require_path "$val_data"

    echo "Launching ${task} on GPU ${gpus}"
    env \
        MKL_SERVICE_FORCE_INTEL=1 \
        CUDA_VISIBLE_DEVICES="$gpus" \
        NPROC_PER_NODE=2 \
        MASTER_PORT="$port" \
        python scripts/launch_cpt_hf_peft_bg.py --log "$log_path" \
        swift sft \
            --model "$MODEL" \
            --adapters "$CPT_ADAPTER" \
            --dataset "$train_data" \
            --val_dataset "$val_data" \
            --template qwen3_thinking \
            --tuner_type lora \
            --torch_dtype bfloat16 \
            --num_train_epochs "$NUM_TRAIN_EPOCHS" \
            --per_device_train_batch_size "$PER_DEVICE_TRAIN_BATCH_SIZE" \
            --per_device_eval_batch_size "$PER_DEVICE_EVAL_BATCH_SIZE" \
            --gradient_accumulation_steps "$GRADIENT_ACCUMULATION_STEPS" \
            --learning_rate "$LEARNING_RATE" \
            --lora_rank 32 \
            --lora_alpha 64 \
            --lora_dropout 0.05 \
            --target_modules q_proj k_proj v_proj o_proj gate_proj up_proj down_proj \
            --max_length "$MAX_LENGTH" \
            --truncation_strategy delete \
            --logging_steps "$LOGGING_STEPS" \
            --eval_steps "$EVAL_STEPS" \
            --save_steps "$SAVE_STEPS" \
            --save_total_limit "$SAVE_TOTAL_LIMIT" \
            --warmup_ratio 0.05 \
            --weight_decay 0.01 \
            --gradient_checkpointing true \
            --dataset_num_proc "$DATASET_NUM_PROC" \
            --dataloader_num_workers "$DATALOADER_NUM_WORKERS" \
            --add_version true \
            --output_dir "$output_dir"
}

require_path "$MODEL/config.json"
require_path "$MODEL/tokenizer.json"
require_path "$CPT_ADAPTER/adapter_config.json"
require_path "$CPT_ADAPTER/adapter_model.safetensors"

launch_task \
    abcx2pm_s1 \
    0,1 \
    29610 \
    ./backup/legacy_Corpora/epr_sft/abcx2pm_s1_shuffle_train.jsonl \
    ./backup/legacy_Corpora/epr_sft/abcx2pm_s1_shuffle_val.jsonl \
    ./output/abcx2pm-s1-sft-from-cpt-r32-hf-1536 \
    "log/sft_abcx2pm_s1_from_cpt_g01_${TS}.log"

launch_task \
    sm2pm_s1 \
    2,3 \
    29611 \
    ./backup/legacy_Corpora/epr_sft/sm2pm_s1_shuffle_train.jsonl \
    ./backup/legacy_Corpora/epr_sft/sm2pm_s1_shuffle_val.jsonl \
    ./output/sm2pm-s1-sft-from-cpt-r32-hf-1536 \
    "log/sft_sm2pm_s1_from_cpt_g23_${TS}.log"
