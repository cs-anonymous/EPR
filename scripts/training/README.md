# 训练脚本说明

## 📁 目录结构

```
scripts/training/
├── README.md                                    # 本文件
│
├── 🔵 SFT 训练脚本
│   ├── launch_sft_epoch2_final.sh              # 启动脚本：SFT Epoch 2 训练（带实时验证）
│   └── train_sft_hf_full_continuous_rounds.py  # 训练脚本：多轮连续 SFT 训练
│
├── 🟢 CPT 训练脚本（保留 2 个版本）
│   ├── launch_cpt_4b_lora_rounds.sh            # 启动脚本：4B 模型 LoRA 训练
│   ├── train_cpt_hf_peft.py                    # 训练脚本：PEFT LoRA 训练
│   ├── launch_cpt_rounds_full_08b_continuous.sh # 启动脚本：0.8B 全量训练
│   └── train_cpt_hf_full_continuous_rounds.py  # 训练脚本：全量参数连续训练
│
└── 🔧 辅助脚本
    ├── eval_on_val_distributed.py              # 验证脚本：分布式验证
    └── log_gpu_metrics.sh                      # GPU 监控脚本
```

## 🔵 SFT 训练

### Epoch 2 训练（当前使用）

**启动命令**：
```bash
bash scripts/training/launch_sft_epoch2_final.sh
```

**功能**：
- ✅ 从 train_S3 模型继续训练
- ✅ 使用 S1+S2+S3 数据（304,542 样本）
- ✅ 每 500 步实时验证（2,000 验证样本）
- ✅ 自动保存最佳模型到 `best_model/`
- ✅ 3 GPU 并行训练
- ✅ 只计算 output 部分的 loss

**参数**：
- 学习率：2e-5 (cosine decay)
- Batch size：1 per GPU
- Gradient accumulation：8
- Max length：4096
- 总步数：12,690 步

## 🟢 CPT 训练

### 1. 4B LoRA 训练（推荐用于大模型）

**启动命令**：
```bash
bash scripts/training/launch_cpt_4b_lora_rounds.sh
```

**用途**：
- 4B+ 大模型训练
- 使用 LoRA 降低显存占用
- 多轮语言 CPT（lan0, lan1, lan2, lan3）

**配置**：
- LoRA rank：64
- LoRA alpha：128
- Target modules：全部线性层
- GPU：3 卡并行

### 2. 0.8B 全量训练（用于小模型）

**启动命令**：
```bash
bash scripts/training/launch_cpt_rounds_full_08b_continuous.sh
```

**用途**：
- 0.8B 小模型训练
- 全参数训练（非 LoRA）
- 连续多轮训练

**配置**：
- 全量参数更新
- GPU：3 卡并行
- 支持断点续训

## 📊 验证功能

### 实时验证（集成在训练中）

**SFT 训练脚本**已集成实时验证：
- 每 N 步自动验证（默认 500 步）
- 输出格式：
```
================================================================================
📊 Validation @ Step 500
================================================================================
  Val Loss: 1.2345  🎯 NEW BEST!
  Best Val Loss: 1.2345
================================================================================
```

### 独立验证脚本

如需单独验证已保存的模型：
```bash
CUDA_VISIBLE_DEVICES=1,2,3 torchrun --nproc_per_node=3 \
  scripts/training/eval_on_val_distributed.py \
  --model output/your_model_path \
  --val-file data/CorporaV2/sft/epr_sft_rounds/val_S.jsonl \
  --max-length 4096
```

## 🗂️ 备份的旧版本

旧的/失败的脚本已移动到：
- `scripts/backup/epoch2_attempts/` - 失败的 SFT Epoch2 尝试
- `scripts/backup/cpt_old_versions/` - 旧的 CPT 版本

## 📝 使用注意事项

1. **GPU 设置**：所有脚本默认使用 GPU 1,2,3（避开 GPU 0）
2. **断点续训**：支持通过 `--resume-from-global-step` 参数恢复训练
3. **显存管理**：自动启用 gradient checkpointing 和 bf16
4. **日志位置**：所有日志保存在 `output/logs/` 目录
5. **验证数据**：确保验证文件存在于 `data/CorporaV2/sft/epr_sft_rounds/`

## 🔍 监控训练

```bash
# 实时查看日志
tail -f output/logs/your_log_file.log

# GPU 使用监控
watch -n 5 nvidia-smi

# 提取训练进度
grep "global_step" output/logs/your_log_file.log | tail -10
```

---

**更新时间**：2026-06-03  
**维护者**：EPR 项目组
