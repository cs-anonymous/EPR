# Qwen3.5-4B-LM-MIDI-Resized CPT LoRA 训练配置（最终版）

## 📋 模型信息

- **基础模型**: Qwen3.5-4B
- **扩展词表**: 248,874 tokens (新增797个LM-MIDI tokens，与0.8B版本相同)
- **对齐词表大小**: 248,960 (128对齐)
- **模型路径**: `/home/sy/EPR/Qwen3.5-4B-LM-MIDI-Resized`

## ⚙️ 训练配置（已确认运行中）

### 硬件配置
- **GPU**: GPU 1-3 (3卡并行) ✅
- **Master Port**: 29541

### LoRA参数
- **LoRA Rank (r)**: 32 ✅
- **LoRA Alpha**: 64
- **LoRA Dropout**: 0.05
- **Target Modules**: q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj
- **Trainable Token Embeddings**: 新增的797个MIDI tokens的embedding可学习 ✅

### 训练超参数
- **可训练参数**: 44,507,648 (1.05%总参数)
- **总参数**: 4,251,897,344
- **Batch Size**: 2 per device ✅
- **梯度累积步数**: 4
- **有效Batch Size**: 2 × 3 × 4 = 24
- **学习率**: 1e-4
- **LR调度器**: Cosine
- **Warmup比例**: 3%
- **最大序列长度**: 2048
- **优化器**: AdamW (torch fused)
- **精度**: BF16
- **梯度检查点**: 启用
- **总训练步数**: 8101 (per round)

### 保存策略
- **保存间隔**: 每500步
- **最大保存数**: 3个checkpoint
- **保存内容**: 仅模型，不保存优化器状态 ✅
- **日志间隔**: 每20步

### 数据配置
- **数据路径**: `data/CorporaV2/language_cpt/rounds/`
- **训练轮次**: 
  1. train_S1 (当前运行中 ⚡)
  2. train_S2
  3. train_Astar1
  4. train_Astar2
  5. train_Astar3
- **训练模式**: 连续训练（每轮从前一轮的final_model继续）

## 📁 文件结构

### 训练脚本
- **启动脚本**: `scripts/training/launch_cpt_4b_lora_rounds.sh`
- **训练脚本**: `scripts/training/train_cpt_hf_peft.py`

### 输出目录
```
output/cpt_qwen35_4b_lora_rounds_20260602_195455/
├── train_S1/          # 当前运行中
│   ├── checkpoint-500/
│   ├── checkpoint-1000/
│   ├── ...
│   ├── final_model/   # 训练完成后
│   ├── train.log
│   └── train_manifest.json
├── train_S2/
├── train_Astar1/
├── train_Astar2/
└── train_Astar3/
```

## 🚀 命令参考

### 启动训练
```bash
nohup bash scripts/training/launch_cpt_4b_lora_rounds.sh > output/logs/cpt_4b_lora_rounds_3gpu_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

### 监控训练
```bash
# 查看训练进程
ps aux | grep train_cpt_hf_peft

# 实时查看训练日志
tail -f output/cpt_qwen35_4b_lora_rounds_20260602_195455/train_S1/train.log

# 查看主日志
tail -f output/logs/cpt_4b_lora_rounds_3gpu_20260602_195455.log

# GPU监控
nvitop
```

### 停止训练
```bash
pkill -f "train_cpt_hf_peft.py"
```

## 📊 当前训练状态

- **开始时间**: 2026-06-02 19:54:55
- **状态**: 运行中 ✅
- **当前轮次**: train_S1 (第1轮/共5轮)
- **总步数**: 8101 步
- **第一步loss**: 16.37
- **预计单步时间**: ~13秒
- **预计单轮时间**: ~29小时

## 🔧 环境变量

```bash
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export MKL_SERVICE_FORCE_INTEL=1
export MKL_THREADING_LAYER=GNU
export CUDA_VISIBLE_DEVICES=1,2,3
```

## 📈 训练特点

### 优势
✅ **内存效率**: LoRA大幅降低显存占用，可用3卡训练4B模型  
✅ **可学习的新token**: 797个MIDI token embeddings可学习  
✅ **仅保存模型**: 不保存优化器状态，节省磁盘空间  
✅ **连续训练**: 5轮渐进式训练，逐步增强模型能力  
✅ **梯度检查点**: 进一步节省显存  

### 与0.8B Full Fine-tuning对比

| 配置项 | 0.8B Full | 4B LoRA |
|--------|-----------|---------|
| 基础模型参数 | ~800M | ~4.25B |
| 可训练参数 | ~800M (100%) | 44.5M (1.05%) |
| 新增tokens | 797 | 797 |
| GPU数量 | 3 | 3 |
| Batch Size | 1 | 2 |
| 有效BS | 24 | 24 |
| 训练方式 | Full FT | LoRA r=32 |
| 保存内容 | 完整模型 | LoRA权重+模型 |
| 显存占用 | 较高 | 较低 |

## 📝 重要修改

1. ✅ 修改了`scripts/training/train_cpt_hf_peft.py`，移除了`trainer.save_state()`，仅保存模型
2. ✅ 配置`save_only_model=True`，checkpoint不包含优化器状态
3. ✅ 使用GPU 1-3（3卡）替代原先的33卡配置
4. ✅ Batch size从1改为2，保持总有效batch size=24

---

**创建时间**: 2026-06-02  
**训练输出**: `output/cpt_qwen35_4b_lora_rounds_20260602_195455/`  
**日志文件**: `output/logs/cpt_4b_lora_rounds_3gpu_20260602_195455.log`
