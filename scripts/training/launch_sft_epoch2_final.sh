#!/bin/bash
# SFT Epoch 2 训练 - 使用修改后的旧脚本（带验证）

set -e

echo "========================================"
echo "SFT Epoch 2 训练（带实时验证）"
echo "========================================"
echo "✅ 从 train_S3 模型继续训练"
echo "✅ 使用 S1+S2+S3 数据"
echo "✅ 每 500 步验证一次"
echo "✅ 自动保存最佳模型"
echo "✅ 使用已验证的训练脚本"
echo "========================================"

# 配置
BASE_MODEL="output/sft_qwen35_08b_from_cpt_6rounds_3gpu_20260531_165450/train_S3/final_model"
ROUNDS_DIR="data/CorporaV2/sft/epr_sft_rounds"
OUTPUT_DIR="output/sft_S_epoch2_final_$(date +%Y%m%d_%H%M%S)"
VAL_FILE="val_S.jsonl"

# 检查
if [ ! -d "$BASE_MODEL" ]; then
    echo "❌ 错误：找不到基础模型 $BASE_MODEL"
    exit 1
fi

if [ ! -f "$ROUNDS_DIR/$VAL_FILE" ]; then
    echo "❌ 错误：找不到验证集 $ROUNDS_DIR/$VAL_FILE"
    exit 1
fi

echo ""
echo "配置："
echo "  基础模型：$BASE_MODEL"
echo "  训练数据：train_S1 + train_S2 + train_S3"
echo "  验证数据：$VAL_FILE"
echo "  输出目录：$OUTPUT_DIR"
echo "  验证频率：每 500 步"
echo "  学习率：2e-5"
echo ""
echo "开始训练..."
echo ""

# 设置环境
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# 启动训练（使用修改后的脚本）
CUDA_VISIBLE_DEVICES=1,2,3 torchrun --nproc_per_node=3 \
  scripts/training/train_sft_hf_full_continuous_rounds.py \
  --model "$BASE_MODEL" \
  --rounds-dir "$ROUNDS_DIR" \
  --rounds train_S1 train_S2 train_S3 \
  --val-file "$VAL_FILE" \
  --output-dir "$OUTPUT_DIR" \
  --num-train-epochs 1 \
  --per-device-train-batch-size 1 \
  --gradient-accumulation-steps 8 \
  --learning-rate 2e-5 \
  --max-length 4096 \
  --eval-steps 500 \
  --save-steps 500 \
  --save-total-limit 3 \
  --logging-steps 20 \
  --seed 42 \
  --bf16 \
  --gradient-checkpointing

echo ""
echo "========================================"
echo "训练完成！"
echo "========================================"
echo "输出目录：$OUTPUT_DIR"
echo "最佳模型：$OUTPUT_DIR/best_model"
echo ""
