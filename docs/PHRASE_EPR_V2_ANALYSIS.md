# Phrase EPR V2 设计分析

## 背景

原始的 Phrase-level EPR 设计使用了较长的上下文，导致 token 数量较大，需要 max_length=4096 才能覆盖所有样本。

## 设计对比

### 原设计（V1）

$$\sigma_{\text{head}} + \sigma_{H_{k-1}} + \sigma_{H_k} + \sigma_{H_{k+1}} + \phi_{H_{k-1}} \rightarrow \phi_{H_k}$$

- **score_snip**: 包含上一整句 (H_{k-1}) + 当前整句 (H_k) + 下一整句 (H_{k+1})
- **perf_context**: 包含上一整句的完整演奏 (φ_{H_{k-1}})

### 新设计（V2）

$$\sigma_{\text{head}} + \sigma_{M_{\text{prev}}} + \sigma_{H_k} + \sigma_{M_{\text{next}}} + \phi_{M_{\text{prev}}} \rightarrow \phi_{H_k}$$

- **score_snip**: 包含上一小节 (M_prev) + 当前整句 (H_k) + 下一小节 (M_next)
- **perf_context**: 只包含上一小节的演奏 (φ_{M_prev})

## 数据分析结果

基于 `sft_data/core-s/phrase_epr.jsonl` (1,447,848 个样本) 的分析：

### 原设计（V1）统计

| 指标 | Mean | Median | P90 | P95 | P99 |
|------|------|--------|-----|-----|-----|
| header | 30.0 | 30.0 | 39.0 | 42.0 | 48.0 |
| score_snip | 147.3 | 139.0 | 205.0 | 230.0 | 312.0 |
| perf_context | 330.6 | 293.0 | 564.0 | 701.0 | 1030.0 |
| perf_target | 348.8 | 302.0 | 582.0 | 732.0 | 1065.0 |
| **input_length** | **507.9** | **468.0** | **775.0** | **920.0** | **1289.0** |
| **total_length** | **856.7** | **771.0** | **1334.0** | **1616.0** | **2310.0** |

### 新设计（V2）估计统计

| 指标 | Mean | Median | P90 | P95 | P99 |
|------|------|--------|-----|-----|-----|
| **new_input_length** | **184.5** | **172.0** | **266.0** | **306.0** | **412.0** |
| **new_total_length** | **533.3** | **476.0** | **835.0** | **1020.0** | **1460.0** |
| saved_tokens | 323.5 | 293.0 | 515.0 | 626.0 | 910.0 |

### Token 节约分析

- **平均节约**: 61.7% 的输入 tokens
- **中位数节约**: 63.0%
- **最小节约**: 0.0% (coldstart 样本)
- **最大节约**: 90.3%

### 覆盖率对比

| max_length | V1 覆盖率 | V2 覆盖率 | 提升 |
|------------|-----------|-----------|------|
| 2048 | 98.27% | **99.74%** | +1.47% |
| 3096 | 99.54% | **100.00%** | +0.46% |
| 4096 | 100.00% | 100.00% | - |

## 关键发现

1. **大幅减少 token 使用**：新设计平均节约 61.7% 的输入 tokens
2. **2048 可覆盖 99.74%**：相比原设计的 98.27%，提升了 1.47 个百分点
3. **3096 可覆盖 100%**：相比原设计需要 4096，节约了 25% 的 context window
4. **保留关键上下文**：
   - 保留了上一小节的乐谱和演奏信息（提供演奏状态）
   - 保留了下一小节的乐谱信息（提供前瞻信息）
   - 去除了冗余的整句上下文

## 建议的 max_length 设置

基于分析结果，建议：

- **推荐使用 2048**：覆盖 99.74% 的样本，性价比最高
- **可选使用 3096**：覆盖 100% 的样本，但只比 2048 多覆盖 0.26%

## 实现

### 新增脚本

1. **`scripts/analyze_phrase_epr_token_length.py`**
   - 分析现有 phrase_epr 数据的 token 长度分布
   - 估计新设计的 token 长度
   - 提供覆盖率分析

2. **`scripts/generate_phrase_epr_v2.py`**
   - 生成新设计的 phrase_epr 数据
   - 输出到 `phrase-based-v2/` 目录
   - 与原脚本 API 兼容

### 使用方法

```bash
# 分析现有数据
python scripts/analyze_phrase_epr_token_length.py \
    --input sft_data/core-s/phrase_epr.jsonl \
    --estimate-new-design

# 生成新设计的数据
python scripts/generate_phrase_epr_v2.py \
    --metadata PianoCoRe/metadata.csv \
    --base_dir . \
    --output_dir sft_data \
    --dataset-filter core-s
```

## 注意事项

1. **只修改了脚本**：按照要求，没有生成或覆盖实际数据
2. **向后兼容**：新脚本的输出格式与原脚本完全兼容
3. **数据字段不变**：仍然包含 `score_header`, `score_snip`, `perf_context`, `perf_target` 等字段
4. **只改变内容**：`score_snip` 和 `perf_context` 的内容变化，但格式不变

## 下一步

1. 使用 `generate_phrase_epr_v2.py` 生成新数据
2. 在训练时将 max_length 从 4096 降低到 2048 或 3096
3. 验证模型性能是否保持或提升
4. 如果效果良好，可以完全替换原有的 phrase_epr 数据生成流程
