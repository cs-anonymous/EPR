# SFT 训练问题诊断：为什么 Loss 不够低？

## 🚨 关键发现：不是 epoch=1 的问题，而是过拟合 + 学习率过低

### 1. 严重的过拟合问题

| 轮次 | 最低 loss 位置 | 最低 loss | 最终 loss | 过拟合差距 | 状态 |
|------|---------------|-----------|-----------|-----------|------|
| train_S3 | **93%** | 1.2404 | 1.2651 | +0.0247 (+2.0%) | ✅ 正常 |
| train_Astar1 | **95%** | 1.2379 | 1.2741 | +0.0362 (+2.9%) | ✅ 正常 |
| **train_Astar2** | **15%** ⚠️ | 1.2305 | 1.2690 | +0.0385 (+3.1%) | 🔴 严重过拟合 |
| train_Astar3 | **78%** | 1.2157 | 1.2502 | +0.0344 (+2.8%) | ⚠️ 轻微过拟合 |

**关键观察**：
- **Astar2 严重过拟合**：最低 loss 出现在训练的 15%，之后持续上升 3.1%
- **Astar3 轻微过拟合**：最低 loss 在 78%，之后上升 2.8%
- 过拟合导致最终 loss 比最佳状态高 2-3%

### 2. 学习率过低问题

```
初始学习率: 5.0e-05
最终学习率: 3.4e-10  (衰减到 0.67%)
```

**问题**：
- 最终学习率只有初始值的 **0.67%**
- 学习率 < 1e-07，模型基本**无法继续学习**
- 这解释了为什么训练后期 loss 趋于平稳

### 3. 数据重复不足

**当前设置**：
- Epoch = **1**
- 每个样本只见过 **1 次**
- 总样本数：~500k（6 轮加起来）

**对比标准做法**：
- 一般 SFT 训练：3-5 epochs
- 每个样本见 3-5 次
- 允许模型充分学习数据模式

## 🔍 为什么会这样？

### 问题 1：学习率调度器设置不当

检查训练脚本的学习率调度：

```python
# 可能的问题：
scheduler = get_linear_schedule_with_warmup(
    optimizer,
    num_warmup_steps=warmup_steps,
    num_training_steps=total_steps  # 这个设置导致学习率过早衰减
)
```

**诊断**：
- 如果 `num_training_steps` 设置为总步数（34,860）
- 到最后学习率会衰减到接近 0
- 模型在后期无法有效学习

### 问题 2：过拟合但学习率太低无法恢复

**Astar2 的情况**：
1. 前 15% 快速下降到 1.2305
2. 然后开始过拟合，loss 上升
3. 但学习率已经衰减，无法跳出局部最优
4. 最终停留在 1.2690

## 💡 解决方案

### 方案 1：多 Epoch 训练（推荐）

```bash
# 训练 3 epochs，使用余弦退火学习率
python scripts/training/train_sft_hf_full_continuous_rounds.py \
  --model <base_model> \
  --rounds-dir data/CorporaV2/sft/epr_sft_rounds \
  --rounds train_S1 train_S2 train_S3 train_Astar1 train_Astar2 train_Astar3 \
  --output-dir output/sft_3epochs \
  --num-train-epochs 3 \
  --learning-rate 5e-5 \
  --lr-scheduler-type cosine \
  --warmup-ratio 0.03 \
  --save-steps 1000 \
  --logging-steps 20
```

**优点**：
- 每个样本见 3 次，充分学习
- 余弦退火避免学习率过早衰减
- 可以从过拟合中恢复

**预期效果**：
- Loss 可能降低到 **1.15-1.18**
- 减少过拟合现象

### 方案 2：单 Epoch + 更好的学习率调度

```bash
# 使用余弦退火，避免线性衰减
python scripts/training/train_sft_hf_full_continuous_rounds.py \
  --model <base_model> \
  --rounds-dir data/CorporaV2/sft/epr_sft_rounds \
  --rounds train_S1 train_S2 train_S3 train_Astar1 train_Astar2 train_Astar3 \
  --output-dir output/sft_cosine \
  --num-train-epochs 1 \
  --learning-rate 5e-5 \
  --lr-scheduler-type cosine \
  --warmup-ratio 0.03 \
  --min-lr-ratio 0.1  # 保持最低学习率为初始值的 10%
```

**优点**：
- 保持更长时间的有效学习率
- 最终学习率不会过低
- 减少过拟合风险

### 方案 3：从最佳 Checkpoint 重新训练

```bash
# 从 Astar2 的最佳点 (step 20620) 重新开始
# 使用更低的学习率，训练更多步
python scripts/training/train_sft_hf_full_continuous_rounds.py \
  --model output/.../train_Astar2/checkpoint-20500 \
  --rounds-dir data/CorporaV2/sft/epr_sft_rounds \
  --rounds train_Astar2 train_Astar3 \
  --output-dir output/sft_from_best \
  --num-train-epochs 2 \
  --learning-rate 1e-5  # 更低的学习率
  --lr-scheduler-type cosine
```

## 📊 当前训练的问题总结

### 为什么 Loss 不够低？

1. **❌ 不是因为 epoch=1**
   - 单 epoch 可以训练好，但需要正确的学习率调度
   
2. **✅ 是因为学习率调度不当**
   - 线性衰减导致最终学习率 < 1e-07
   - 模型后期无法有效学习

3. **✅ 是因为过拟合**
   - Astar2 在 15% 处过拟合，loss 上升 3.1%
   - Astar3 在 78% 处过拟合，loss 上升 2.8%
   - 学习率太低，无法从过拟合中恢复

4. **✅ 是因为数据重复不足**
   - 每个样本只见 1 次
   - 复杂的表演生成任务可能需要更多重复

## 🎯 推荐行动方案

### 立即可做（最小成本）

1. **检查学习率调度器设置**
   ```bash
   grep -A 10 "scheduler\|lr_scheduler" scripts/training/train_sft_hf_full_continuous_rounds.py
   ```

2. **如果使用线性调度，改为余弦调度**
   - 修改脚本中的 `lr_scheduler_type`
   - 从当前最佳模型继续训练

### 中等成本

3. **从最佳 checkpoint 继续训练 1-2 个 epoch**
   - 使用 Astar3 step 33000 的 checkpoint（最低 loss 1.2157）
   - 余弦学习率，初始值 1e-5
   - 预期可以进一步降低到 1.15-1.18

### 长期优化

4. **重新训练整个流程，3 epochs**
   - 使用余弦学习率调度
   - 预期最终 loss: 1.15-1.18
   - 但成本高（3x 训练时间）

## 📈 预期改进

如果采用方案 1（3 epochs + 余弦调度）：

| 当前 | 预期 | 改进 |
|------|------|------|
| 最终 loss: 1.2502 | **1.15-1.18** | **-6% to -8%** |
| 最低 loss: 1.2157 | **1.13-1.16** | **-7% to -10%** |
| 过拟合差距: 2.8% | **<1%** | 显著减少 |

## 结论

**问题不在于 epoch=1，而在于：**
1. ❌ 学习率调度不当（过早衰减）
2. ❌ 过拟合但无法恢复（学习率太低）
3. ⚠️ 可能需要更多数据重复（2-3 epochs）

**建议优先级**：
1. 🔥 **高优先级**：检查并修复学习率调度器
2. 🔥 **高优先级**：从最佳 checkpoint 继续训练 1-2 epochs
3. ⚡ **中优先级**：重新训练 3 epochs（如果时间允许）

---

**生成时间**: 2026-06-03  
**数据来源**: SFT 训练日志 + 收敛分析
