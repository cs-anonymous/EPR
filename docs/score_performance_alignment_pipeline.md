# Score-Performance Alignment Pipeline

完整的乐谱-演奏对齐数据生成流程文档。

---

## 目录

1. [概述](#概述)
2. [数据流图](#数据流图)
3. [步骤详解](#步骤详解)
4. [脚本使用](#脚本使用)
5. [符号说明](#符号说明)
6. [输出文件结构](#输出文件结构)

---

## 概述

本流程将乐谱（XML/MXL）和演奏 MIDI 转换为带有层次结构（H/M）和注释的标记化 TSV 格式。

**核心步骤**：
1. **Step 1**: XML/MXL → score.abcx
2. **Step 2**: 构建 H/M 结构 + 写入 aligned ABCX
3. **Step 3**: 写入 annotated score TSV
4. **Step 4**: 投影到 performance TSV

**输出数据**：
- 1,600 个 score.abcx
- 7,252 个 score_aligned.abcx + score_structure.json
- 7,252 个 score.annotated_score.mid.tsv
- 129,419 个 performance.mid.tsv

---

## 数据流图

```
┌─────────────┐
│ XML/MXL (σ₀)│
└──────┬──────┘
       │ [Step 1]
       │ 01_build_score_abcx.py
       ↓
┌─────────────────┐
│ score.abcx (σ)  │
└────────┬────────┘
         │
         │ + score MIDI (ψ)
         │
         │ [Step 2]
         │ 02_build_hm_structure.py
         ↓
┌──────────────────────────────┐
│ H/M 结构 + aligned ABCX (σ*) │
│ • score_structure.json       │
│ • score_aligned.abcx         │
└──────────┬───────────────────┘
           │
           │ + score MIDI (ψ)
           │ + annotations (σ)
           │
           │ [Step 3]
           │ 03_write_annotated_tsv.py
           ↓
┌────────────────────────────────┐
│ annotated score TSV (ψ*)       │
│ score.annotated_score.mid.tsv  │
└────────────────────────────────┘

┌──────────────────────┐
│ performance MIDI (φ) │
└──────────┬───────────┘
           │
           │ + H/M 结构
           │ + alignment NPZ
           │
           │ [Step 4]
           │ 04_project_performance_tsv.py
           ↓
┌────────────────────────────┐
│ performance TSV (φ*)       │
│ performance_refined.mid.tsv│
└────────────────────────────┘
```

---

## 步骤详解

### Step 1: 构建 score.abcx

**脚本**: `scripts/01_build_score_abcx.py`

**输入**: 
- `PianoCoRe/raw/Composer/Piece/score.mxl` (XML/MXL 格式)

**输出**: 
- `data/miditsv/Composer/Piece/score.abcx` (σ)

**功能**:
从 XML/MXL 转换生成 ABCX 格式，直接输出到最终目录。

**执行**:
```bash
python scripts/01_build_score_abcx.py \
  --raw-dir PianoCoRe/raw \
  --output-dir data/miditsv \
  --jobs 32 \
  --force
```

**ABCX 格式示例**:
```
<V000>
[G3 A3 B3]
<V001>
[C4 D4 E4]
```

---

### Step 2: 构建 H/M 结构 + 写入 aligned ABCX

**脚本**: `scripts/02_build_hm_structure.py`

**输入**:
- `data/miditsv/Composer/Piece/score.abcx` (σ)
- `PianoCoRe/raw/Composer/Piece/score_*.mid` (ψ)

**输出**:
- `data/miditsv/Composer/Piece/score_structure.json` (H/M 结构)
- `data/miditsv/Composer/Piece/score_aligned.abcx` (σ*)

**功能**:
1. **提取小节网格**: 从 score MIDI 解析时间签名和小节边界
2. **映射 ABCX 内容**: 将 ABCX 小节映射到 MIDI 小节
3. **分组乐句**: 将小节分组为乐句（H）
4. **写入结构**: 输出 JSON 格式的 H/M 层次结构
5. **写入对齐 ABCX**: 插入 H/M 标记

**执行**:
```bash
python scripts/02_build_hm_structure.py \
  --metadata data/score_metadata.csv \
  --pianocore-root PianoCoRe \
  --jobs 32
```

**H/M 结构**:
- **H (Hierarchical)**: 乐句级别，包含多个小节
- **M (Measure)**: 小节级别，对应 MIDI 的 measure

**Aligned ABCX 格式**:
```
<H><V000>
<M><V000>
[G3 A3 B3]
<M><V000>
[C4 D4 E4]
```

**Structure JSON 格式**:
```json
{
  "measures": [
    {"id": 0, "start_tick": 0, "duration_tick": 480}
  ],
  "phrases": [
    {"id": 0, "start_measure": 0, "end_measure": 3}
  ],
  "measure_to_phrase": {"0": 0, "1": 0, "2": 0}
}
```

---

### Step 3: 写入 annotated score TSV

**脚本**: `scripts/03_write_annotated_tsv.py`

**输入**:
- `data/miditsv/Composer/Piece/score_structure.json` (H/M 结构)
- `PianoCoRe/raw/Composer/Piece/score_*.mid` (ψ)
- `data/miditsv/Composer/Piece/score.abcx` (σ, 含注释)

**输出**:
- `data/miditsv/Composer/Piece/score.annotated_score.mid.tsv` (ψ*)

**功能**:
1. **标记化 MIDI 事件**: 音符、踏板、时间签名
2. **添加 H/M 标记**: 插入乐句和小节行
3. **提取注释**: 从 ABCX 提取力度、演奏法、表情等
4. **合并注释**: 将注释插入到对应位置

**执行**:
```bash
python scripts/03_write_annotated_tsv.py \
  --metadata data/score_metadata.csv \
  --pianocore-root PianoCoRe \
  --jobs 32
```

**注释类型**:
- **力度**: pppp, ppp, pp, p, mp, mf, f, ff, fff, ffff
- **演奏法**: accent, staccato, tenuto, sfz
- **装饰音**: arpeggio, turn, trill
- **范围**: crescendo, diminuendo
- **踏板**: down, up
- **表情**: a_tempo, dolce, rit, rall 等

**TSV 格式**:
```
H	0	0	1940
M	0	0	480
dynamic	p
G3	80	480	0
accent
A3	75	240	0
pedal	down
```

**列说明**:
- **H 行**: `H phrase_id start_tick duration_tick`
- **M 行**: `M measure_id start_tick duration_tick`
- **音符行**: `pitch velocity duration voice_id`
- **注释行**: `annotation_type value` 或 `annotation_type`

---

### Step 4: 投影到 performance TSV

**脚本**: 
- S-tier: `scripts/04_project_performance_tsv.py`
- A*-tier: `scripts/process_astar_performances.py`

**输入**:
- `data/miditsv/Composer/Piece/score_structure.json` (H/M 结构)
- `PianoCoRe/refined/Composer/Piece/performance_refined.mid` (φ)
- `PianoCoRe/refined/Composer/Piece/performance_refined_align.npz` (对齐数据)

**输出**:
- `data/miditsv/Composer/Piece/performance_refined.mid.tsv` (φ*)

**功能**:
通过对齐数据（NPZ）将 H/M 结构投影到演奏 MIDI 的时间轴上。

**执行**:
```bash
# S-tier
python scripts/04_project_performance_tsv.py \
  --metadata data/performance_S_metadata.csv \
  --pianocore-root PianoCoRe \
  --output-dir data/miditsv \
  --jobs 32 \
  --tier all \
  --overwrite-tsv

# A*-tier
python scripts/process_astar_performances.py \
  --metadata data/performance_Astar_metadata.csv \
  --pianocore-root PianoCoRe \
  --output-dir data/miditsv \
  --jobs 32 \
  --overwrite-tsv
```

**对齐原理**:
- NPZ 文件包含 score MIDI 和 performance MIDI 之间的对应关系
- 通过对齐关系，将 score 的 H/M 时间戳映射到 performance 时间戳

**Performance TSV 格式**:
```
H	0	0	2260
M	0	0	520
G3	71	495	0
A3	64	235	0
pedal	down
```

---

## 脚本使用

### 完整流程

执行所有步骤：

```bash
python scripts/run_pipeline.py --jobs 32
```

**选项**:
- `--jobs N`: 并行进程数（默认：32）
- `--skip-step1`: 跳过 Step 1
- `--skip-step2`: 跳过 Step 2
- `--skip-step3`: 跳过 Step 3
- `--skip-step4-s`: 跳过 Step 4 (S-tier)
- `--skip-step4-astar`: 跳过 Step 4 (A*-tier)

### 单独执行步骤

```bash
# Step 1
python scripts/01_build_score_abcx.py \
  --raw-dir PianoCoRe/raw \
  --output-dir data/miditsv \
  --jobs 32

# Step 2
python scripts/02_build_hm_structure.py \
  --metadata data/score_metadata.csv \
  --jobs 32

# Step 3
python scripts/03_write_annotated_tsv.py \
  --metadata data/score_metadata.csv \
  --jobs 32

# Step 4 (S-tier)
python scripts/04_project_performance_tsv.py \
  --metadata data/performance_S_metadata.csv \
  --jobs 32
```

---

## 符号说明

| 符号 | 含义 | 文件 |
|------|------|------|
| **σ₀** | 原始 XML/MXL | `score.mxl` |
| **σ** | 原始 ABCX | `score.abcx` |
| **σ*** | 对齐的 ABCX（带 H/M 标记） | `score_aligned.abcx` |
| **ψ** | 原始 score MIDI | `score_*.mid` |
| **ψ*** | 带注释的 score TSV | `score.annotated_score.mid.tsv` |
| **φ** | 原始 performance MIDI | `performance_refined.mid` |
| **φ*** | performance TSV | `performance_refined.mid.tsv` |
| **H/M** | 层次结构 | H=乐句，M=小节 |

---

## 输出文件结构

```
data/miditsv/
└── Composer/
    └── Piece/
        ├── score.abcx                          # σ (原始)
        ├── score_aligned.abcx                  # σ* (对齐)
        ├── score_structure.json                # H/M 结构
        ├── score.annotated_score.mid.tsv       # ψ* (带注释)
        ├── performance_1.mid.tsv               # φ* (演奏 1)
        ├── performance_2.mid.tsv               # φ* (演奏 2)
        └── piece_interpretation.json           # 元数据
```

---

## 技术细节

### H/M 层次结构

**H (Hierarchical - 乐句)**:
- 包含多个连续的小节
- 通常对应音乐的乐句或段落
- 用于高层次的结构分析

**M (Measure - 小节)**:
- 对应 MIDI 的一个 measure
- 由时间签名定义边界
- 是最小的结构单位

### 对齐算法

1. **小节检测**: 使用时间签名和音符时间
2. **乐句映射**: 匹配 ABCX 内容到 MIDI 小节
3. **重复展开**: 自动检测和展开重复段落

### 注释提取

从 ABCX 的 XML 结构中提取：
- `<dynamics>`: 力度标记
- `<articulations>`: 演奏法
- `<ornaments>`: 装饰音
- `<direction>`: 表情和踏板

---

## 数据统计

**生成数据总览**:
- ✅ Step 1: 1,600 个 score.abcx
- ✅ Step 2: 7,252 个 structure.json + aligned ABCX
- ✅ Step 3: 7,252 个 annotated score TSV
- ✅ Step 4 (S-tier): 62,969 个 performance TSV
- ✅ Step 4 (A*-tier): 66,450 个 performance TSV

**总计**: 129,419 个 performance TSV 文件

---

## 相关文档

- **流程图**: `docs/score_performance_alignment_tikz.pdf`
- **脚本说明**: `scripts/README.md`
- **脚本结构**: `docs/FINAL_SCRIPT_STRUCTURE.md`

---

## 常见问题

### Q: 为什么 Step 2 同时输出 structure.json 和 aligned ABCX？

A: 因为它们是紧密耦合的。构建 H/M 结构后立即写入 aligned ABCX 是最自然的流程，避免了不必要的中间步骤。

### Q: 为什么不生成中间的 score.mid.tsv？

A: Step 3 直接生成带注释的 TSV (ψ*)，避免了生成中间文件再合并的冗余步骤。

### Q: orphan scores 是什么？

A: 没有对应 score MIDI 的乐谱。这些乐谱只能生成 aligned ABCX，无法生成 TSV。

### Q: 如何验证生成的数据？

A: 检查输出文件：
```bash
# 检查 H/M 结构
cat data/miditsv/Composer/Piece/score_structure.json | jq .

# 检查 TSV 格式
head -20 data/miditsv/Composer/Piece/score.annotated_score.mid.tsv
```

---

## 更新日志

**2026-05-29**: 
- 重构脚本结构，将 Step 2 和 Step 3a 合并
- 简化符号系统，ψ* 直接表示带注释的 TSV
- 更新所有文档和流程图

**初始版本**: 完整的数据生成流程
