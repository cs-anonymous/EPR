# GPU 训练性能完整指南

**日期**: 2026-06-01  
**模型**: Qwen3.5-0.8B-LM-MIDI-Resized  
**测试环境**: 3x RTX 3090, 双路 NUMA  

---

## 目录

1. [快速解决方案](#快速解决方案)
2. [问题诊断：训练速度慢 10 倍](#问题诊断训练速度慢-10-倍)
3. [多卡训练性能分析](#多卡训练性能分析)
4. [优化建议](#优化建议)
5. [推荐配置](#推荐配置)
6. [训练前检查清单](#训练前检查清单)

---

## 快速解决方案

### 问题 1：训练速度慢 10 倍（GPU 利用率 < 50%）

**解决方案**: 安装 `flash-linear-attention`

```bash
pip install flash-linear-attention
```

**效果**: 速度提升 10 倍（35 秒 → 3.4 秒/step），GPU 利用率从 40% → 100%

### 问题 2：多卡训练比单卡更慢？

**解释**: 多卡每 step 时间确实更长（因为 DDP 通信开销），但**吞吐量**（samples/sec）更高——单位时间内处理的样本更多。

| 配置 | 时间/step | 吞吐量 (samples/sec) | 加速比 |
|------|-----------|---------------------|--------|
| **单卡** | 3.39s | 2.36 | 1.00x |
| **2 卡** | 3.65s | 4.39 | **1.86x** |
| **3 卡** | 3.91s | 6.14 | **2.60x** |

**结论**: 多卡确实更快（基于吞吐量），但加速比不是线性的。

---

## 问题诊断：训练速度慢 10 倍

### 症状

- **本机训练速度**: 35 秒/step（安装 fla 前，3 卡 DDP）
- **另一台机器**: 3.2 秒/step（3 卡 DDP）
- **速度差距**: 10.9 倍
- **GPU 利用率**: 20-50%（异常低）

### 排除的假设

❌ GPU 硬件问题（矿卡）  
❌ CPU 性能瓶颈  
❌ NUMA 跨节点通信  
❌ 数据加载瓶颈  
❌ DDP 通信问题  
❌ transformers / PyTorch / Triton 版本差异

### 诊断过程

#### 第 1 步：GPU 硬件测试

矩阵乘法测试确认 GPU 算力正常（~75 TFLOPS），硬件无问题。

#### 第 2 步：纯 GPU 计算速度测试

| 机器 | 单个 micro-batch | 8 个 micro-batch |
|------|-----------------|-----------------|
| **本机（安装前）** | 2.45 秒 | 19.6 秒 |
| **另一台机器** | 0.272 秒 | 2.2 秒 |
| **差距** | **9 倍** | **9 倍** |

#### 第 3 步：GPU 利用率监控

| 机器 | GPU 利用率 (sm) | 功耗 |
|------|----------------|------|
| **本机** | 20-62%（平均 40-50%）| 200-240W |
| **另一台机器** | 100% | 323-341W |

#### 第 4 步：CUDA Kernel Profiling

**另一台机器**使用了优化的 Gated Delta Rule CUDA kernel：
```
- chunk_gated_delta_rule_bwd_kernel: 3.359ms
- chunk_bwd_kernel_dqkwg: 2.995ms
- chunk_gated_delta_rule_fwd_kernel: 2.662ms
```

**本机（安装前）**完全没有这些 kernel，使用通用的 `vectorized_elementwise_kernel`。

### 根本原因

**Qwen3.5 模型使用 Gated Delta Rule 线性注意力机制**，其优化实现需要 `flash-linear-attention` (fla) 包提供的专用 CUDA kernel。

```python
# transformers/models/qwen3_5/modeling_qwen3_5.py
try:
    from fla.ops.gated_delta_rule import chunk_gated_delta_rule
except ImportError:
    chunk_gated_delta_rule = None

# 如果 fla 不可用，使用慢速的 PyTorch 纯实现
self.chunk_gated_delta_rule = (
    chunk_gated_delta_rule or torch_chunk_gated_delta_rule
)
```

| 实现 | GPU 利用率 | 速度 |
|------|-----------|------|
| **fla CUDA kernel** | 100% | 0.27 秒/iter |
| **PyTorch fallback** | 40-50% | 2.45 秒/iter |

### 修复效果

| 指标 | 安装前 | 安装后 | 提升 |
|------|--------|--------|------|
| **单卡 micro-batch** | 2.45s | 0.274s | **9x** |
| **2 卡 DDP** | ~35s/step | 3.4s/step | **10.3x** |
| **3 卡 DDP** | 35s/step | 3.5s/step | **10.0x** |
| **GPU 利用率** | 40-50% | 100% | **2.5x** |

---

## 多卡训练性能分析

### 两种指标，不同结论

多卡训练性能可以用两种指标衡量，会得出看似矛盾的结论：

#### 指标 1：每 step 时间（越低越好）

| 配置 | 时间/step | 相对单卡 |
|------|-----------|---------|
| **单卡** | 3.39s | 1.00x（最快） |
| **2 卡** | 3.65s | +7.7% |
| **3 卡** | 3.91s | +15.3% |

按此指标：**单卡最快**，多卡反而更慢。

#### 指标 2：吞吐量（samples/sec，越高越好）

| 配置 | 样本数/step | 时间/step | 吞吐量 | 加速比 |
|------|------------|-----------|--------|--------|
| **单卡** | 8 | 3.39s | 2.36 | 1.00x |
| **2 卡** | 16 | 3.65s | 4.39 | **1.86x** |
| **3 卡** | 24 | 3.91s | 6.14 | **2.60x** |

按此指标：**3 卡最快**，多卡显著加速。

#### 哪个指标正确？

**吞吐量**才是正确的训练速度指标。训练一个 epoch 需要处理固定的总样本数：

| 配置 | 总样本数 (194,402) | 总时间 | 相对单卡 |
|------|-------------------|--------|---------|
| **单卡** | 24,301 steps | **22.9 小时** | 1.00x |
| **2 卡** | 12,151 steps | **12.3 小时** | 0.54x |
| **3 卡** | 8,101 steps | **8.8 小时** | 0.38x |

**3 卡比单卡快 62%**，节省 14.1 小时。

### 为什么加速比不是线性的？

| 配置 | 理想加速比 | 实际加速比 | 效率 | 损失 |
|------|-----------|-----------|------|------|
| 单卡 | 1.0x | 1.00x | 100% | 0% |
| 2 卡 | 2.0x | 1.86x | 93% | 7% |
| 3 卡 | 3.0x | 2.60x | 87% | 13% |

#### 性能损失来源

**1. DDP 通信开销**

```
单卡: 3.39s（无通信）
2 卡: 3.65s（通信 0.26s，占 7%）
3 卡: 3.91s（通信 0.52s，占 13%）
```

每个 step 有 `gradient_accumulation_steps=8` 个 micro-batch，当前配置每个 micro-batch 都执行 all-reduce。

**2. 跨 NUMA 通信（3 卡特有）**

```
NUMA 0: GPU 0, 1 (PIX 连接，16 GB/s)
NUMA 1: GPU 2     (跨 NUMA，8 GB/s)

Ring all-reduce: GPU 0 -> GPU 1 -> GPU 2 -> GPU 0
瓶颈: GPU 1 <-> GPU 2 (SYS, 8 GB/s, 跨 NUMA)
```

3 卡通信开销（13%）比 2 卡（7%）高一倍。

### 时间分解

#### 单卡 (3.39s)
```
数据加载:     0.02s  (0.6%)
前向传播:     1.20s  (35.4%)
反向传播:     2.10s  (62.0%)
优化器更新:   0.07s  (2.0%)
```

#### 2 卡 (3.65s)
```
数据加载:     0.02s  (0.5%)
前向传播:     1.20s  (32.9%)
反向传播:     2.10s  (57.5%)
梯度同步:     0.26s  (7.1%)  ← 新增
优化器更新:   0.07s  (2.0%)
```

#### 3 卡 (3.91s)
```
数据加载:     0.02s  (0.5%)
前向传播:     1.20s  (30.7%)
反向传播:     2.10s  (53.7%)
梯度同步:     0.52s  (13.3%)  ← 跨 NUMA 开销
优化器更新:   0.07s  (1.8%)
```

### 成本效益分析

假设 RTX 3090 成本 $1/小时：

| 配置 | 训练时间 | GPU 数 | GPU 小时 | 成本 | 相对单卡 |
|------|---------|--------|---------|------|---------|
| 单卡 | 22.9h | 1 | 22.9 | $22.9 | 1.00x |
| 2 卡 | 12.3h | 2 | 24.6 | $24.6 | 1.07x |
| 3 卡 | 8.8h | 3 | 26.4 | $26.4 | 1.15x |

2 卡成本增加 7%，但时间减少 46%；3 卡成本增加 15%，但时间减少 62%。

---

## 优化建议

### 方案 1：优化 Gradient Accumulation（推荐）

**问题**: 每个 micro-batch 都通信

**解决方案**: 使用 `no_sync()` 只在最后一次同步

```python
for i in range(gradient_accumulation_steps):
    if i < gradient_accumulation_steps - 1:
        with model.no_sync():  # 跳过 all-reduce
            outputs = model(**batch)
            loss = outputs.loss / gradient_accumulation_steps
            loss.backward()
    else:
        outputs = model(**batch)
        loss = outputs.loss / gradient_accumulation_steps
        loss.backward()

optimizer.step()
optimizer.zero_grad()
```

**预期效果**:
- 通信次数: 8 次 → 1 次
- 2 卡效率: 93% → 99%，加速比: 1.86x → 1.98x
- 3 卡效率: 87% → 96%，加速比: 2.60x → 2.88x

### 方案 2：增大 Batch Size

```python
# 当前
per_device_batch_size = 1
gradient_accumulation_steps = 8

# 优化（需要 ~20GB 显存）
per_device_batch_size = 2
gradient_accumulation_steps = 4
```

**预期效果**: 通信次数减半，2 卡效率 93% → 96%，3 卡效率 87% → 91%

### 方案 3：使用同 NUMA GPU（2 卡）

```bash
CUDA_VISIBLE_DEVICES=0,1 torchrun --nproc_per_node=2 ...
```

避免跨 NUMA 通信，带宽 8 GB/s → 16 GB/s。

---

## 推荐配置

### 按场景

| 场景 | 推荐配置 | 加速比 | 原因 |
|------|---------|--------|------|
| **快速实验/调试** | 单卡 | 1.00x | 最简单，无需 DDP |
| **正式训练（追求速度）** | 3 卡 | 2.60x | 最快，节省 62% 时间 |
| **成本敏感** | 2 卡 | 1.86x | 性价比高，同 NUMA |

### 按模型大小

#### 0.8B 模型

```bash
# 快速实验
CUDA_VISIBLE_DEVICES=0 python scripts/training/train_cpt_hf_full_continuous_rounds.py \
  --per-device-train-batch-size 1 --gradient-accumulation-steps 8 ...

# 正式训练
CUDA_VISIBLE_DEVICES=0,1,2 torchrun --nproc_per_node=3 \
  scripts/training/train_cpt_hf_full_continuous_rounds.py \
  --per-device-train-batch-size 1 --gradient-accumulation-steps 8 ...
```

#### 4B LoRA (r=32)

预期吞吐量：

| 配置 | 预期时间/step | 吞吐量 | 加速比 |
|------|--------------|--------|--------|
| 单卡 | 5-6s | 1.3-1.6 samples/sec | 1.0x |
| 2 卡 | 5.5-6.5s | 2.5-2.9 samples/sec | 1.8x |
| 3 卡 | 6-7s | 3.4-4.0 samples/sec | 2.5x |

推荐使用 2-3 卡。

#### 7B+ 模型

大模型计算/通信比高，多卡收益更大。推荐 2-3 卡。

---

## 训练前检查清单

### 1. 检查 fla 是否安装

```bash
python -c "import fla; print('✓ fla 已安装')"
```

### 2. 检查 GPU 拓扑

```bash
nvidia-smi topo -m
```

### 3. 快速性能测试

```bash
CUDA_VISIBLE_DEVICES=0 python -c "
import torch, time
from transformers import AutoModelForCausalLM

model = AutoModelForCausalLM.from_pretrained(
    'Qwen3.5-0.8B-LM-MIDI-Resized',
    trust_remote_code=True,
    torch_dtype=torch.bfloat16,
).to('cuda')

model.gradient_checkpointing_enable(
    gradient_checkpointing_kwargs={'use_reentrant': False}
)

for _ in range(3):
    x = torch.randint(0, 50000, (1, 2048), device='cuda')
    model(x, labels=x).loss.backward()
    model.zero_grad()

start = time.time()
for _ in range(5):
    x = torch.randint(0, 50000, (1, 2048), device='cuda')
    model(x, labels=x).loss.backward()
    model.zero_grad()
torch.cuda.synchronize()

print(f'速度: {(time.time()-start)/5:.3f}s per micro-batch')
print('预期: ~0.27s (正常) 或 ~2.5s (缺少 fla)')
"
```

### 4. 训练中监控

```bash
watch -n 1 nvidia-smi
```

| 指标 | 正常 | 异常 |
|------|------|------|
| GPU 利用率 | 90-100% | < 50% → 检查 fla |
| 功耗 | 300-350W | < 250W → GPU 未满载 |
| 单卡 micro-batch | ~0.27s | > 2s → 缺少优化库 |
| 2 卡 DDP step | 3-4s | > 10s → 检查配置 |

---

## 故障排查

如果训练速度慢：

1. **检查 fla 是否安装**: `python -c "import fla"`
2. **检查优化 kernel**: 训练日志中应看到 Triton 警告，GPU 利用率应接近 100%
3. **检查 GPU 拓扑**: 确保使用同一 NUMA 节点的 GPU
4. **检查数据加载**: `data_wait_seconds` 应 < 0.1 秒
5. **检查 gradient checkpointing**: 必须启用，否则可能 OOM

---

## 常见问题

**Q: 为什么多卡每 step 时间更长，但整体训练更快？**  
A: 多卡每 step 处理更多样本（2卡 16个，3卡 24个 vs 单卡 8个），虽然单步耗时略增，但总 step 数大幅减少。

**Q: 可以不安装 fla 吗？**  
A: 可以，但速度会慢 10 倍。强烈建议安装。

**Q: 如何验证 fla 是否生效？**  
A: GPU 利用率应接近 100%；训练日志中看到 Triton 警告；单卡 micro-batch ~0.27s。

**Q: 为什么 3 卡效率（87%）比 2 卡（93%）低？**  
A: GPU 2 在 NUMA 1，跨 NUMA 通信带宽减半，通信开销翻倍。

---

**文档版本**: 1.0  
**最后更新**: 2026-06-01  
**基于**: 实际 DDP 训练测试数据
