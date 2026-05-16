# SPIRE SFT 数据全景

本文档描述 SPIRE (Score-Performance Interaction Rendering Engine) 监督微调训练数据的完整图谱：三类任务、三类数据源、原始数据来源、处理流程与算法。

---

## 一、三类任务

### 1.1 EPR (Expressive Performance Rendering)

**目标**: 给定乐谱，生成对应的表演 MIDI 事件。

| 粒度 | 公式 | 说明 |
|------|------|------|
| Measure | `σ_{M_k} → φ_{M_k}` | 给定第 k 小节乐谱，生成该小节表演 |
| Phrase | `σ_{H_k} → φ_{H_k}` | 给定第 k 乐句乐谱，生成该乐句表演 |

- 输入: aligned ABCX (`σ`) — 带 `H`(phrase) / `M`(measure) 标记的乐谱
- 输出: MIDI-TSV 格式表演事件 (`φ`) — 包含 pitch、duration、velocity、pedal
- 任务类型: `coldstart`(首单元) / `main`(中间单元) / `ending`(末单元)
- `score_snip` 包含前后各一个单元的上下文

### 1.2 Score Language Learning

**目标**: 学习乐谱语言模型，支持续写与遮蔽重建。

| 粒度 | 续写 | 遮蔽重建 |
|------|------|----------|
| Measure | `σ_head + σ_{M_k} → σ_{M_{k+1}}` | `σ_head + f(σ_{M_k}) → σ_{M_k}` |
| Phrase | `σ_head + σ_{H_k} → σ_{H_{k+1}}` | `σ_head + f(σ_{H_k}) → σ_{H_k}` |

**f-mask 变体 (Score)**:

| mask 类型 | 说明 | 算法 |
|-----------|------|------|
| `acc` | 遮去升降号 | 移除 `^`/`_`/`=` accidental 符号 |
| `treble` | 遮去高音谱声部(右手) | 对 ` ; ` 分割的第一声部做 note pitch mask |
| `bass` | 遮去低音谱声部(左手) | 对 ` ; ` 分割的第二声部做 note pitch mask |
| `label` | 遮去表情、力度、速度标记 | 移除 `!...!` 和 `"..."` 标记 |

Note pitch mask 规则: 将音符字母 `A-Ga-g` 替换为 `X`，保留节奏数字、括号、小节线、空格、分号。

### 1.3 Performance Language Learning

**目标**: 学习表演语言模型，支持续写与遮蔽重建。

| 粒度 | 续写 | 遮蔽重建 |
|------|------|----------|
| Measure | `φ_{M_k} → φ_{M_{k+1}}` | `g(φ_{M_k}) → φ_{M_k}` |
| Phrase | `φ_{H_k} → φ_{H_{k+1}}` | `g(φ_{H_k}) → φ_{H_k}` |

**g-mask 变体 (Performance)**:

| mask 类型 | 说明 | 算法 |
|-----------|------|------|
| `timing` | 遮去 onset/timing | 替换 onset 列为 `[MASK_TIMING]` |
| `velocity` | 遮去力度 | 替换 velocity 列为 `[MASK_VEL]` |
| `duration` | 遮去音长 | 替换 duration 列为 `[MASK_DUR]` |
| `pedal` | 遮去踏板事件 | 过滤掉所有 `P...` 踏板行 |

---

## 二、三类数据源

### 2.1 Unpaired Score (仅有乐谱，无表演对齐)

| 数据 | 路径 | 数量 | 说明 |
|------|------|------|------|
| Aligned ABCX | `PianoCoRe/orphan_abcx/*_aligned.abcx` | **4,820** | 仅乐谱，无对应 MIDI 表演 |

**用途**: Score Language Learning 任务（续写 + mask 重建）

### 2.2 Unpaired Performance (仅有表演，无乐谱对齐)

保留规则：仅使用 PianoCoRe `tier_b=True` 且不属于 `tier_a` 的 performance-only 数据。原始 `PianoCoRe/orphan_tsv/` 目录中有 58,799 个 TSV，按 tier B+ 口径实际保留 **53,227** 个。

| 数据 | 路径 | 数量 | 说明 |
|------|------|------|------|
| MIDI-TSV | `PianoCoRe/orphan_tsv/**/*.tsv` | **53,227** | 仅表演，无对应乐谱，`tier_b=True`, `tier_a=False` |

**用途**: Performance Language Learning 任务（续写 + mask 重建）

### 2.3 Paired Data (乐谱 + 表演对齐)

保留规则：仅使用 PianoCoRe `tier_a=True` 的 paired score-performance 数据；`tier_a_star=True` 是其更高置信子集。

| 数据 | 路径 | 数量 | 说明 |
|------|------|------|------|
| Aligned ABCX | `PianoCoRe/aligned/**/*_aligned.abcx` | **1,584** | 乐谱（已对齐，tier A+） |
| MIDI-TSV | `PianoCoRe/aligned/**/*.tsv` | **155,956** | 表演（已对齐，tier A+ 且已有 TSV） |

**用途**: EPR 任务 + Score/Performance Language Learning 任务

### 数据总量汇总

| 数据类型 | 数量 | 用途 |
|----------|------|------|
| Aligned ABCX (总) | 6,404 (4,820 + 1,584) | Score Language |
| MIDI-TSV (总) | 209,183 (53,227 + 155,956) | Performance Language |
| 配对对 (ABCX+TSV) | 155,956 | EPR |

---

## 三、原始数据来源

### 3.1 Downloaded Scores → Unpaired ABCX

四类公开乐谱数据集，共 4,820 个文件：

| 数据集 | 原始格式 | 原始数量 | 处理后 ABCX | 转换方式 |
|--------|----------|----------|-------------|----------|
| PDMX | `.mxl` (MusicXML) | 3,000 | 2,941 | xml2abc → clean → abc2abcx |
| OpenScore_Lieder | `.mxl` (MusicXML) | 1,462 | 1,345 | xml2abc → clean → abc2abcx |
| DCMLab | `.mscx` (MuseScore) | 378 | 343 | MuseScore3 → .musicxml → xml2abc → ... |
| KernScores_sonatas | `.krn` (Humdrum) | 197 | 191 | music21 → .musicxml → xml2abc → ... |

### 3.2 PianoCoRe → Paired + Unpaired Performance

PianoCoRe 原始数据包含 1,607 首曲目的 `.mxl` 乐谱和 244,157 个 MIDI 表演文件：

| 原始数据 | 路径 | 数量 |
|----------|------|------|
| Raw Score MXL | `PianoCoRe/raw/` | 1,607 |
| Raw Performance MIDI | `PianoCoRe_output/` | 244,157 |
| Quality Metadata | `PianoCoRe/metadata.csv` | 250,046 行 |

**筛选流程**:
1. Paired/EPR 过滤: `tier_a=True`（A+），当前已有 TSV 的 paired performance 为 **155,956** 个。
2. Paired score 转换: `tier_a=True` 的 unique score 为 **1,584** 个 aligned ABCX。
3. Unpaired Performance 过滤: `tier_b=True` 且 `tier_a=False`，当前已有 TSV 的 orphan performance 为 **53,227** 个。
4. Performance Language 总 TSV: paired A+ **155,956** + unpaired B-only **53,227** = **209,183**。

---

## 四、数据处理 Pipeline

### 4.1 Score 转换 Pipeline

```
原始乐谱 (MXL/MSCX/KRN)
        │
        ▼
┌─────────────────────┐
│ Step 1: 转 MusicXML  │  MSCX→MuseScore3 / KRN→music21 / MXL 直接
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│ Step 2: xml2abc     │  MusicXML → ABC (xml2abc.py)
│                     │  - 提取音符、节奏、声部
│                     │  - 保留表情/力度/速度标记
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│ Step 3: clean_for_  │  abcjs 兼容后处理
│         abcjs()     │  - 修复和弦转义、连音线、八度标记
│                     │  - 处理 %%MIDI 指令
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│ Step 4: to_standard_│  ABC → ABCX (voice interleaving)
│         abcx()      │  - 多声部按小节交错: "voice1 ; voice2 ; ..."
│                     │  - 过滤歌词行 (w:/W:/s:/S:)
│                     │  - 输出单行单小节格式
└─────────────────────┘
        │
        ▼
    ABCX 文件 (data/score_processed/)
```

### 4.2 Aligned ABCX 生成 Pipeline

```
ABCX 文件
    │
    ▼
┌─────────────────────┐
│ parse_abcx_header() │  提取 X:/T:/C:/K:/M:/L:/Q:/%% 行
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ parse_abcx_body()   │  按 | 分割小节，过滤 V: 行
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ create_aligned_abcx()│  每 4 小节为一组标记为 H1, H2, ...
│                     │  每个小节前加 M1, M2, ... + TAB
└─────────────────────┘
    │
    ▼
Aligned ABCX (PianoCoRe/orphan_abcx/)
```

**Aligned ABCX 格式示例**:
```
X:1
T:Sonata No. 1
C:Mozart
K:C
M:4/4
H1
M1	[CEG] [DFA] | [EGB] [FAc] |
M2	[GBd] [Ace] | [Bdf] [ceg] |
M3	...
M4	...
H2
M5	...
```

### 4.3 Performance (MIDI-TSV) 生成 Pipeline

```
原始 MIDI + 对齐文件 (.npz) + 乐谱 ABCX
        │
        ▼
┌─────────────────────┐
│ MIDI → 音符列表      │  pretty_midi 解析
│ + Alignment         │  将 MIDI 音符对齐到乐谱小节
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│ TSV 格式化           │  按小节/乐句分组
│                     │  H1\t0\t416      (乐句标记)
│                     │  M1\t0\t104      (小节标记)
│                     │  60:100\t80      pitch:duration\tvelocity
│                     │  P64             pedal
└─────────────────────┘
        │
        ▼
    MIDI-TSV 文件
```

---

## 五、SFT 数据生成算法

### 5.1 Score Language 生成

```python
for each aligned_abcx_file (6,404 total):
    score = AlignedABCXParser.parse(file)
    # score = {header, measures: {M1: "...", M2: "...", ...},
    #          phrases: {H1: [M1,M2,M3,M4], ...}}

    # --- Continuation ---
    for i in range(len(measure_ids) - 1):
        input =  f"M{i}\t{score.measures[M{i}]}"
        target = f"M{i+1}\t{score.measures[M{i+1}]}"
        save_continuation(input, target)

    # --- Mask ---
    for i in range(len(measure_ids) - 1):
        content = score.measures[M{i}]
        mask_type = random.choice(["acc", "treble", "bass", "label"])
        masked = SCORE_MASKS[mask_type](content)
        if masked != content:
            input =  f"M{i}\t{masked}"
            target = f"M{i}\t{content}"
            save_mask(input, target, mask_type)
```

每文件上限 50 个样本（continuation 和 mask 各最多 25 个）。

### 5.2 Performance Language 生成

```python
for each tsv_file:
    perf = TSVParser.parse(file)
    # perf = {header, measures, measure_durations, phrases, phrase_durations}

    # --- Continuation ---
    for i in range(len(measure_ids) - 1):
        input =  f"M{i}:{duration}\n{perf.measures[M{i}]}"
        target = f"M{i+1}:{duration}\n{perf.measures[M{i+1}]}"
        save_continuation(input, target)

    # --- Mask ---
    for i in range(len(measure_ids) - 1):
        mask_type = random.choice(["timing", "velocity", "duration", "pedal"])
        masked = PERF_MASKS[mask_type](perf.measures[M{i}])
        save_mask(masked, perf.measures[M{i}], mask_type)
```

每文件上限 25 个样本（continuation 和 mask 各最多 12-13 个）。

### 5.3 EPR 生成

```python
for each row in metadata.csv:
    if is_refined and refined_recall >= 0.7:
        score_snip = extract_context(aligned_abcx, target_measure, window=1)
        perf_events = extract_tsv_measure(aligned_tsv, target_measure)
        save_epr(score_snip, perf_events, task_type)
```

---

## 六、当前 SFT 数据统计

### Measure-based

| 任务 | 文件 | 样本数 | 大小 |
|------|------|--------|------|
| EPR | `measure_epr.jsonl` | 6,217,115 | 7.0 GB |
| Perf Lang Continuation | `measure_perf_lang_continuation.jsonl` | 21,810,156 | 19 GB |
| Perf Lang Mask | `measure_perf_lang_mask.jsonl` | 20,471,555 | 18 GB |
| Score Lang Continuation | `measure_score_lang_continuation.jsonl` | 646,564 | 262 MB |
| Score Lang Mask | `measure_score_lang_mask.jsonl` | 386,867 | 166 MB |
| **Measure 合计** | | **49,532,257** | **44.4 GB** |

### Phrase-based

| 任务 | 文件 | 样本数 | 大小 |
|------|------|--------|------|
| EPR | `phrase_epr.jsonl` | 2,261,655 | 7.0 GB |
| Score Lang Continuation | `phrase_score_lang_continuation.jsonl` | 158,030 | 140 MB |
| Score Lang Mask | `phrase_score_lang_mask.jsonl` | 113,985 | 104 MB |
| **Phrase 合计** | | **2,533,670** | **7.2 GB** |

### 总计

| 类别 | 样本数 |
|------|--------|
| EPR | 8,478,770 |
| Performance Language | 42,281,711 |
| Score Language | 1,305,446 |
| **原始 JSONL 总计** | **52,065,927** |
| Swift messages train/val | 43,587,157 |

---

## 七、重要脚本与运行参数

### 7.1 主流程脚本

| 阶段 | 脚本 | 作用 | 主要输入 | 主要输出 |
|------|------|------|----------|----------|
| 外部乐谱清洗/转换 | `scripts/score_corpus_pipeline.py` | 将 PDMX、OpenScore、DCMLab、KernScores 等外部乐谱整理成 ABCX | `data/score/` | `data/score_processed/` |
| 单个/批量 MusicXML 转 ABCX | `xml_to_abcx.py` | MusicXML/MXL → ABCX，保留力度、连线、踏板、速度等谱面信息 | `.musicxml/.xml/.mxl` | `.abcx` |
| Orphan score 对齐标记 | `process_orphan_abcx.py` | 为未配对 ABCX 添加 `H`/`M` 乐句和小节标记 | `data/score_processed/` | `PianoCoRe/orphan_abcx/` |
| PianoCoRe score-performance 对齐 | `scripts/align_score_performance.py` | 从 PianoCoRe refined MIDI/npz/ABCX 生成 aligned ABCX 与 performance TSV | `PianoCoRe/` | `PianoCoRe/aligned/` |
| Language Learning 数据 | `generate_language_learning_data.py` | 生成 score/performance continuation 与 mask 数据 | `PianoCoRe/aligned/`, `PianoCoRe/orphan_*` | `sft_data/measure-based/`, `sft_data/phrase-based/` |
| EPR 数据 | `generate_sft_data.py` | 基于 metadata 生成 measure/phrase EPR 样本 | `PianoCoRe/metadata.csv`, `PianoCoRe/aligned/` | `sft_data/measure-based/`, `sft_data/phrase-based/` |
| Swift 格式转换 | `prepare_sft_data.py` | 合并 Language Learning JSONL，转成 MS-SWIFT messages 格式并切 train/val | `sft_data/*-based/*.jsonl` | `sft_data/swift_format/` |
| 训练 | `sft_language.sh` | 训练合并后的 score/performance language SFT 数据 | `sft_data/swift_format/language_*.jsonl` | `output/language-sft/` |

### 7.2 推荐运行顺序

#### Step 1: 外部 score-only 数据转 ABCX

```bash
# 生成/检查外部 score 语料清单
python scripts/score_corpus_pipeline.py inventory \
  --score-root data/score \
  --work-root data/score_work \
  --processed-root data/score_processed

# 批量转换 MXL/MusicXML 到 ABCX；--drop-harmony 可减少和声分析文本污染
python scripts/score_corpus_pipeline.py convert-mxl \
  --src-root data/score_work \
  --out-root data/score_processed \
  --pattern '**/*.mxl' \
  --jobs 16 \
  --timeout-s 120 \
  --drop-harmony
```

单文件调试时用：

```bash
python xml_to_abcx.py path/to/score.mxl \
  --output path/to/score.abcx \
  --drop-harmony
```

#### Step 2: 生成 orphan aligned ABCX

```bash
python process_orphan_abcx.py \
  --input_dir data/score_processed \
  --output_dir PianoCoRe/orphan_abcx \
  --phrase_size 4 \
  --pattern '**/*.abcx'
```

#### Step 3: 生成 PianoCoRe 配对 aligned 数据

```bash
python scripts/align_score_performance.py \
  --metadata PianoCoRe/metadata.csv \
  --pianocore-root PianoCoRe \
  --output-dir PianoCoRe/aligned \
  --tier a \
  --jobs 16
```

调试单个作品：

```bash
python scripts/align_score_performance.py \
  --metadata PianoCoRe/metadata.csv \
  --pianocore-root PianoCoRe \
  --output-dir PianoCoRe/aligned \
  --tier a \
  --piece-filter "Gavotte" \
  --limit 1 \
  --jobs 1
```

#### Step 4: 生成 Language Learning SFT

```bash
python generate_language_learning_data.py \
  --aligned_dir PianoCoRe/aligned \
  --orphan_abcx_dir PianoCoRe/orphan_abcx \
  --orphan_tsv_dir PianoCoRe/orphan_tsv \
  --output_dir sft_data \
  --task all \
  --max_score_per_piece 50 \
  --max_perf_per_piece 25
```

只跑 score 或 performance 分支时可把 `--task` 改成：

| 参数 | 生成内容 |
|------|----------|
| `measure_score` | 小节级 score continuation/mask |
| `phrase_score` | 乐句级 score continuation/mask |
| `measure_perf` | 小节级 performance continuation/mask |
| `phrase_perf` | 乐句级 performance continuation/mask |
| `all` | score measure+phrase + performance measure |

#### Step 5: 生成 EPR SFT

```bash
python generate_sft_data.py \
  --metadata PianoCoRe/metadata.csv \
  --base_dir . \
  --output_dir sft_data \
  --task all \
  --min_recall 0.7
```

只跑单一粒度时可把 `--task` 改成 `measure_epr` 或 `phrase_epr`。

#### Step 6: 转 MS-SWIFT messages 格式

```bash
python prepare_sft_data.py
```

注意：`prepare_sft_data.py` 当前没有命令行参数，会固定读取 `sft_data/measure-based/`、`sft_data/phrase-based/`，并输出到 `sft_data/swift_format/`。

#### Step 7: 训练

```bash
# 默认使用 GPU 0,1,2,3
bash sft_language.sh

# 例：只用 GPU 0,1
CUDA_VISIBLE_DEVICES=0,1 NPROC_PER_NODE=2 MASTER_PORT=29501 bash sft_language.sh
```

### 7.3 辅助与修复脚本

| 脚本 | 用途 | 常用参数 |
|------|------|----------|
| `scripts/verify_abcx.py` | 检查 ABCX 结构问题 | `--input-dir PianoCoRe/score` |
| `scripts/fix_abcx_repeats.py` | 修复 `::` 重复记号嵌入小节内容的问题 | `--input-dir PianoCoRe/score --output-dir PianoCoRe/score` |
| `scripts/reconvert_abcx.py` | 从 PianoCoRe raw MXL 重新批量生成 `score.abcx` | `--jobs 16 --limit 100` |
| `scripts/analyze_measure_variants.py` | 分析同一作品不同演奏的小节数变体 | 输出到 `output/reports/` |
| `scripts/fix_language_learning_masks.py` | 修正旧版 mask token / instruction 字段 | 用于旧数据迁移，不是主流程必跑 |
| `scripts/gen_examples_100.py` | 每类任务抽样 100 条用于人工检查 | 用于 spot check，不是主流程必跑 |

---

最后更新: 2026-05-16
