# Language CPT Corpora Generation

完整的语言 CPT 训练数据生成流程文档。

---

## 概述

本流程从 miditsv 数据生成用于语言模型持续预训练（CPT）的训练数据。

**核心特性**：
- **Tokenizer**: Qwen3.5-0.8B-LM-MIDI-Resized
- **并行度**: 32 线程
- **分批策略**: S-tier 分 2 批，A*-tier 分 3 批
- **Token 计数**: 通过 `<XXX>` 正则表达式计数，绕过 tokenizer

**输出数据**：
- `data/CorporaV2/language_cpt/` - 原始 JSON/JSONL 文件
- `data/CorporaV2/language_cpt_rounds/` - 多轮训练数据（round1-5）

---

## 数据流图

```
data/miditsv/
├── score.annotated_score.mid.tsv
└── performance_refined.mid.tsv

         │
         │ [Step 1]
         │ build_language_cpt_measure_jsons.py
         │ • 按小节边界切分
         │ • Token 计数（<XXX> 正则）
         │ • 过滤超长序列
         ↓

data/CorporaV2/language_cpt/
├── performance_Astar_midi.json      (A*-tier 演奏)
├── performance_S_midi.jsonl         (S-tier 演奏)
└── annotated_score_midi.jsonl       (带注释的乐谱)

         │
         │ [Step 2]
         │ build_language_cpt_rounds.py
         │ • S-tier 分 2 批
         │ • A*-tier 分 3 批
         │ • 每批内部打乱
         ↓

data/CorporaV2/language_cpt_rounds/
├── round1.jsonl    (S-tier batch 1/2)
├── round2.jsonl    (S-tier batch 2/2)
├── round3.jsonl    (A*-tier batch 1/3)
├── round4.jsonl    (A*-tier batch 2/3)
└── round5.jsonl    (A*-tier batch 3/3)
```

---

## 步骤详解

### Step 1: 生成 measure-boundary JSON 文件

**脚本**: `scripts/data_processing/build_language_cpt_measure_jsons.py`

**功能**:
1. **读取 TSV 文件**: 从 miditsv 读取 annotated score 和 performance TSV
2. **按小节切分**: 在 M (measure) 边界处切分序列
3. **Token 计数**: 使用正则表达式 `<[^>]+>` 匹配 token，绕过 tokenizer
4. **智能打包**: 尽量将多个小节打包在一起，直到接近 `max_tokens`
5. **保持完整性**: 不在小节中间切断，单个小节即使超过限制也会保留
6. **生成 JSON**: 输出为 JSON 或 JSONL 格式

**注意**: 生成的 chunk 可能略微超过 `max_tokens`（通常不超过 10%），因为：
- 小节边界优先：不会在小节中间切断
- 累积策略：在添加小节后才检查是否超过限制

**执行**:
```bash
python scripts/data_processing/build_language_cpt_measure_jsons.py \
  --tokenizer ./Qwen3.5-0.8B-LM-MIDI-Resized \
  --max-tokens 2048 \
  --workers 32 \
  --datasets astar performance_s annotated_score \
  --output-dir data/CorporaV2/language_cpt
```

**参数说明**:
- `--tokenizer`: Tokenizer 路径（用于初始化，但 token 计数用正则）
- `--max-tokens`: 最大 token 数（默认：2048）
- `--workers`: 并行进程数（默认：CPU 核心数）
- `--datasets`: 要生成的数据集（可选：astar, performance_s, annotated_score）
- `--output-dir`: 输出目录

**输出文件**:
- `performance_Astar_midi.json` - A*-tier 演奏数据（JSON 数组）
- `performance_S_midi.jsonl` - S-tier 演奏数据（JSONL）
- `annotated_score_midi.jsonl` - 带注释的乐谱数据（JSONL）
- `language_cpt_measure_summary.json` - 生成统计

**JSON 格式**:
```json
{
  "text": "<H> 0 0 2260\n<M> 0 0 520\n<G3> 71 495 0\n...",
  "source": "Composer/Piece/performance_refined.mid.tsv",
  "token_count": 1847
}
```

---

### Step 2: 构建多轮训练数据

**脚本**: `scripts/data_processing/build_language_cpt_rounds.py`

**功能**:
1. **读取 JSON 文件**: 从 Step 1 的输出读取数据
2. **分批**: 
   - S-tier: 分为 2 批（round1, round2）
   - A*-tier: 分为 3 批（round3, round4, round5）
3. **打乱**: 每批内部随机打乱
4. **输出 JSONL**: 每轮一个 JSONL 文件

**执行**:
```bash
python scripts/data_processing/build_language_cpt_rounds.py \
  --corpora-dir data/CorporaV2/language_cpt \
  --output-dir data/CorporaV2/language_cpt_rounds \
  --seed 42
```

**参数说明**:
- `--corpora-dir`: Step 1 的输出目录
- `--output-dir`: 输出目录
- `--seed`: 随机种子（默认：42）

**分批策略**:
```python
ROUND_PLANS = [
    RoundPlan("round1", "performance_S_midi.jsonl", "performance_S", 0, 2),
    RoundPlan("round2", "performance_S_midi.jsonl", "performance_S", 1, 2),
    RoundPlan("round3", "performance_Astar_midi.json", "performance_Astar", 0, 3),
    RoundPlan("round4", "performance_Astar_midi.json", "performance_Astar", 1, 3),
    RoundPlan("round5", "performance_Astar_midi.json", "performance_Astar", 2, 3),
]
```

**输出文件**:
- `round1.jsonl` - S-tier batch 1/2
- `round2.jsonl` - S-tier batch 2/2
- `round3.jsonl` - A*-tier batch 1/3
- `round4.jsonl` - A*-tier batch 2/3
- `round5.jsonl` - A*-tier batch 3/3

---

## 快速执行

### 使用脚本

```bash
bash scripts/data_processing/generate_language_cpt.sh
```

### 手动执行

```bash
# Step 1: 生成 measure-boundary JSON
python scripts/data_processing/build_language_cpt_measure_jsons.py \
  --tokenizer ./Qwen3.5-0.8B-LM-MIDI-Resized \
  --max-tokens 2048 \
  --workers 32 \
  --output-dir data/CorporaV2/language_cpt

# Step 2: 构建多轮数据
python scripts/data_processing/build_language_cpt_rounds.py \
  --corpora-dir data/CorporaV2/language_cpt \
  --output-dir data/CorporaV2/language_cpt_rounds \
  --seed 42
```

---

## Token 计数机制

### 为什么绕过 tokenizer？

使用正则表达式 `<[^>]+>` 直接计数 token，而不是调用 tokenizer，原因：

1. **性能**: 正则匹配比 tokenizer 快得多
2. **一致性**: LM-MIDI token 格式固定（`<XXX>`），正则计数准确
3. **简单**: 不需要加载完整的 tokenizer

### 实现

```python
TOKEN_RE = re.compile(r"<[^>]+>")

def count_tokens_fast(text: str) -> int:
    """Count tokens by regex pattern matching."""
    return len(TOKEN_RE.findall(text))
```

### 示例

```
输入文本:
<H> 0 0 2260
<M> 0 0 520
<G3> 71 495 0
<A3> 64 235 0

Token 计数: 12
(<H>, 0, 0, 2260, <M>, 0, 0, 520, <G3>, 71, 495, 0, ...)
```

---

## 输出文件结构

```
data/CorporaV2/
├── language_cpt/
│   ├── performance_Astar_midi.json          # A*-tier 演奏
│   ├── performance_S_midi.jsonl             # S-tier 演奏
│   ├── annotated_score_midi.jsonl           # 带注释的乐谱
│   ├── language_cpt_measure_summary.json    # 统计信息
│   ├── astar_measure_errors.jsonl           # A*-tier 错误
│   ├── performance_s_measure_errors.jsonl   # S-tier 错误
│   └── annotated_score_measure_errors.jsonl # Score 错误
│
└── language_cpt_rounds/
    ├── round1.jsonl    # S-tier batch 1/2
    ├── round2.jsonl    # S-tier batch 2/2
    ├── round3.jsonl    # A*-tier batch 1/3
    ├── round4.jsonl    # A*-tier batch 2/3
    └── round5.jsonl    # A*-tier batch 3/3
```

---

## 数据统计

查看生成统计：

```bash
cat data/CorporaV2/language_cpt/language_cpt_measure_summary.json
```

**示例输出**:
```json
{
  "tokenizer": "./Qwen3.5-0.8B-LM-MIDI-Resized",
  "max_tokens": 2048,
  "datasets": ["astar", "performance_s", "annotated_score"],
  "performance_Astar_midi.json": 45230,
  "performance_S_midi.jsonl": 38120,
  "annotated_score_midi.jsonl": 12450,
  "errors": {
    "astar": 125,
    "performance_s": 89,
    "annotated_score": 34
  }
}
```

---

## 训练使用

生成的数据可用于多轮 CPT 训练：

```bash
# Round 1 (S-tier batch 1)
swift sft --dataset data/CorporaV2/language_cpt_rounds/round1.jsonl ...

# Round 2 (S-tier batch 2)
swift sft --dataset data/CorporaV2/language_cpt_rounds/round2.jsonl ...

# Round 3-5 (A*-tier)
swift sft --dataset data/CorporaV2/language_cpt_rounds/round3.jsonl ...
```

---

## 常见问题

### Q: 为什么 S-tier 分 2 批，A*-tier 分 3 批？

A: 基于数据量和训练策略：
- S-tier 数据量较小，分 2 批足够
- A*-tier 数据量较大，分 3 批可以更细粒度地控制训练

### Q: 如何修改分批策略？

A: 编辑 `scripts/data_processing/build_language_cpt_rounds.py` 中的 `ROUND_PLANS`：

```python
ROUND_PLANS = [
    RoundPlan("round1", "performance_S_midi.jsonl", "performance_S", 0, 3),  # 改为 3 批
    RoundPlan("round2", "performance_S_midi.jsonl", "performance_S", 1, 3),
    RoundPlan("round3", "performance_S_midi.jsonl", "performance_S", 2, 3),
    # ...
]
```

### Q: 如何验证生成的数据？

A: 检查 JSONL 文件：

```bash
# 查看前几条
head -5 data/CorporaV2/language_cpt_rounds/round1.jsonl | jq .

# 统计行数
wc -l data/CorporaV2/language_cpt_rounds/*.jsonl
```

---

## 生成结果（2026-05-29）

### Step 1 输出

- **A*-tier**: 485,731 chunks (5.0GB)
- **S-tier**: 311,694 chunks (3.2GB)
- **Annotated Score**: 47,627 chunks (486MB)
- **总计**: 844,052 个训练样本 (8.6GB)
- **错误**: 0 个 ✅

### Step 2 输出

| Round | 文件大小 | 总样本数 | Score 样本 | Performance 样本 |
|-------|---------|---------|-----------|----------------|
| round1 | 2.1GB | 207,177 | 47,627 | 159,550 (S 1/2) |
| round2 | 2.0GB | 199,771 | 47,627 | 152,144 (S 2/2) |
| round3 | 2.4GB | 225,635 | 47,627 | 178,008 (A* 1/3) |
| round4 | 1.9GB | 184,892 | 47,627 | 137,265 (A* 2/3) |
| round5 | 2.3GB | 218,085 | 47,627 | 170,458 (A* 3/3) |
| **总计** | **10.7GB** | **1,035,560** | **238,135** | **797,425** |

---

## 相关文档

- **训练文档**: `backup/docs/CPT_LANGUAGE_TRAINING.md` (历史参考)
- **Loss 分析**: `docs/LOSS_ANALYSIS.md`

---

## 更新日志

**2026-05-29**: 创建完整的 Language CPT 数据生成文档
