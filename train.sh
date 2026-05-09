#!/bin/bash
# Qwen3.5-4B SFT Training Script using MS-SWIFT
# Hardware: 4x RTX 3090 (24GB each)
# Strategy: LoRA with DDP (Distributed Data Parallel)
# Note: DeepSpeed requires system CUDA toolkit for compilation.
#       If you install CUDA toolkit, add `--deepspeed zero2` for ZeRO optimization.

MODEL_PATH="./Qwen3.5-4B"
TRAIN_DATA="./sft_data/sample_train.jsonl"
VAL_DATA="./sft_data/sample_val.jsonl"
OUTPUT_DIR="./output/qwen3.5-4b-sft"

swift sft \
    --model "$MODEL_PATH" \
    --model_type qwen3_5 \
    --train_type lora \
    --dataset "$TRAIN_DATA" \
    --val_dataset "$VAL_DATA" \
    --num_train_epochs 3 \
    --per_device_train_batch_size 1 \
    --per_device_eval_batch_size 1 \
    --gradient_accumulation_steps 8 \
    --learning_rate 2e-4 \
    --lora_rank 16 \
    --lora_alpha 32 \
    --lora_dropout 0.1 \
    --target_modules all-linear \
    --max_length 2048 \
    --logging_steps 5 \
    --eval_steps 50 \
    --save_steps 50 \
    --save_total_limit 3 \
    --warmup_ratio 0.05 \
    --weight_decay 0.01 \
    --gradient_checkpointing true \
    --dataloader_num_workers 4 \
    --output_dir "$OUTPUT_DIR" \
    --torch_dtype bfloat16
