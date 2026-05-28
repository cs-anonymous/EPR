# Score-Performance 对齐与 TSV 生成流程

> 本文档描述从 PianoCoRe metadata.csv 出发，生成 `score_aligned.abcx`、`score_structure.json` 和 performance MIDI-TSV（`.tsv`）的完整流程。

## 0. 核心规则：以 metadata.csv 为索引

**一定要以 metadata 作为索引处理文件，不要依赖目录扫描。**

原因：
- 不同 score dataset（PDMX、ASAP、MuseScore、ATEPP）使用不同的 score MIDI 文件名（`score_PDMX_refined.mid`、`score_ASAP_refined.mid`、`score_MS_refined.mid`、`score_ATEPP_refined.mid`）
- 目录扫描只能找到固定模式的文件，会漏掉非 PDMX 的 score
- `metadata.csv` 的每一行已经明确给出了 `refined_score_midi_path`、`refined_performance_midi_path`、`refined_alignment_path`，三者一一对应
- 所有 184,230 条 refined 路径都已验证存在于磁盘上

正确做法：
1. 读取 `metadata.csv`
2. 按 tier 过滤（如 `tier_a == True`）
3. 过滤有 ABCX 文件的条目（`piece_path` 存在于 `PianoCoRe_output`）
4. 按 score 文件分组（`refined_score_midi_path` + `piece_path`）
5. 每个分组作为一个任务：构建 score 结构 + 处理该 score 下所有 performances

## 1. 整体流程概览

```
PianoCoRe/refined/<Composer>/<Piece>/
├── score_PDMX_refined.mid          → Step 1: 提取逻辑小节
├── <perf>_refined.mid              → Step 3: 对齐演奏
└── <perf>_refined_align.npz        → Step 3: 对齐映射

PianoCoRe_output/<Composer>/<Piece>/
└── score.abcx                      → Step 2: 解析乐谱结构

                          ↓

PianoCoRe/aligned/<Composer>/<Piece>/
├── score.abcx                      (原始 ABCX 副本)
├── score_aligned.abcx              (展开后的 ABCX，含乐句标记)
├── score_structure.json            (小节、乐句、映射关系)
└── <perf>_refined.mid.tsv          (演奏 MIDI-TSV，含乐句和小节结构)
```

## 2. 数据依赖

### 2.1 输入文件

| 来源 | 文件 | 用途 |
|------|------|------|
| `PianoCoRe/refined/` | `score_{dataset}_refined.mid`（PDMX/ASAP/MS/ATEPP） | Score MIDI，提取逻辑小节边界 |
| `PianoCoRe/refined/` | `<perf>_refined.mid` | 演奏 MIDI，提取演奏时间 |
| `PianoCoRe/refined/` | `<perf>_refined_align.npz` | note-level 对齐，映射演奏→Score MIDI |
| `PianoCoRe_output/` | `score.abcx` | ABCX 乐谱，解析结构与乐句 |
| `PianoCoRe_output/` | `score.abcx`（经 `fix_abcx_repeats.py` 修复） | 修复 `::` 内嵌问题的 ABCX |

### 2.2 工具依赖

| 脚本 | 功能 |
|------|------|
| `backup/scripts_legacy/fix_abcx_repeats.py` | 修复 ABCX 中内嵌的 `::` 标记 |
| `scripts/align_score_performance.py` | 主流程：提取小节 → 解析 ABCX → 对齐演奏 → 生成 TSV |
| `wave-roll/midi_tsv.py` | MIDI-TSV 模块，解析 MIDI、构建 tempo map |
| `xml2abc/xml2abc.py` | MusicXML → ABCX 转换（生成 `PianoCoRe_output`） |

## 3. 流程步骤

### Step 0: 修复 ABCX 中的 `::` 标记

MXL→ABCX 转换时，volta 边界（`::`）可能被错误地内嵌在小节内容中而非作为小节分隔符。修复脚本会将每个含 `::` 的小节段拆分为两个独立小节。

```bash
python backup/scripts_legacy/fix_abcx_repeats.py --input-dir PianoCoRe_output --output-dir PianoCoRe_output
```

修复前：
```
|[FAd]6 ; D,2 A,,2 D,,2 :: fg ; D,2|     ← :: 内嵌在小节中
```

修复后：
```
|[FAd]6 ; D,2 A,,2 D,,2 :: | fg ; D,2|   ← :: 成为独立小节分隔
```

### Step 1: 提取 Score MIDI 逻辑小节

**输入**: `score_{dataset}_refined.mid`（由 metadata.csv 指定）

**处理**:
1. 解析 Score MIDI 的 tempo map 和 time signature
2. 根据拍号计算每个小节的 tick 边界
3. 将 tick 转换为秒，确定每个小节的起止时间
4. 将音符分配到对应小节，记录 `start_note_idx` 和 `end_note_idx`

**输出**: `List[ScoreMeasure]` — 每个逻辑小节包含：
- `measure_num`: 小节编号（1-indexed）
- `start_time` / `end_time`: 秒
- `start_note_idx` / `end_note_idx`: 音符索引范围
- `time_signature`: 拍号

### Step 2: 解析 ABCX 结构并建立映射

**输入**: `score.abcx` + Step 1 的 `ScoreMeasure` 列表

#### 2.1 解析 ABCX 小节

解析 ABCX body（`K:` 之后），按 `|` 分割小节。每个小节包含：
- 多声部内容（以 `;` 分隔）
- `::` 标记（第一结尾/第二结尾边界）
- `:` 标记（乐句结尾）

`_parse_abcx_measures()` 将 ABCX 段落拆分为带编号的小节列表，并标记每个小节是否为乐句边界（phrase closer/starter）。

#### 2.2 建立 MIDI→ABCX 映射

`build_midi_to_abcx_mapping()` 将 Score MIDI 小节映射到 ABCX 小节：
1. 为 MIDI 和 ABCX 小节构建内容签名（音符数 + 音级集合）
2. 前 `min(num_midi, num_abcx)` 个 MIDI 小节顺序映射
3. 剩余 MIDI 小节通过滑动窗口匹配找到最优偏移量
4. 超出 ABCX 数量的极端情况使用循环回退

**输出**: `midi_to_abcx: dict[int, int]` — MIDI 小节号 → ABCX 小节号

#### 2.3 展开 ABCX 内容到每个 MIDI 小节

`build_midi_measure_content()` 将 ABCX 内容映射到每个 MIDI 小节，同时剥离 `::` 和 `:` 标记（这些是记谱符号，不属于实际音符内容）。

#### 2.4 识别乐句

`build_midi_phrases()` 在展开的 MIDI 小节列表上识别乐句：
1. 使用 4 小节为一组的启发式策略
2. 最大 8 小节为一组
3. 末尾不足 4 小节则合并到前一个乐句
4. 任何少于 4 小节的乐句在后期处理中合并

**输出**: `List[Phrase]` — 每个乐句包含 `phrase_id`（如 `H1`）和 `measures`（MIDI 小节号列表）

### Step 3: 对齐 Performance MIDI 与 Score

**输入**: `score_{dataset}_refined.mid`（由 metadata.csv 指定） + `<perf>_refined.mid` + `<perf>_refined_align.npz` + Step 2 的 `ScoreStructure`

#### 3.1 构建对齐时间映射

`align_performance_with_score()`:
1. 从 `align.npz` 读取 `perf_idx`（Score 音符索引 → 演奏音符索引）
2. 将 Score 音符时间映射到演奏音符时间
3. 按 MIDI 小节聚合演奏时间
4. 计算连续时间边界：
   - 每个小节取演奏时间的 min/max
   - 相邻小节边界取中点，确保 `M[i].end == M[i+1].start`
5. 计算乐句级连续时间范围
6. 按乐句变化生成输出：乐句首行 + 每小节行

#### 3.2 生成 MIDI-TSV

`generate_performance_tsv_with_phrases()`:
1. 从演奏 MIDI 提取音符和踏板事件
2. 检测调号
3. 输出 TSV 格式（10ms tick 精度）：
   - `HX` 行：乐句头，`HX \t start_tick \t end_tick`
   - `MX` 行：小节头，`MX \t start_tick \t end_tick`
   - `P` 行：踏板事件，`P \t rel_tick \t value`
   - 音符行：`pitch:duration \t rel_tick \t velocity`

**输出**: `<perf>_refined.mid.tsv`

## 4. 输出文件格式

### 4.1 `score_aligned.abcx`

展开后的 ABCX 文件，每个 Score MIDI 小节一行（而非原始 ABCX 的紧凑记谱形式）：

```
X:1
T:Gavotte
C:Georg Friedrich H\"andel
%%score 1 2
L:1/8
M:4/4
K:G
I:linebreak $
H1
M1	GA ; z2
M2	B2 AG d2 ef ; G,2 G,,2 G,2 F,2
...
H2
M5	[Bg]6 ag ; E,2 E,,2 E,2 ^C,2
...
```

- `H1`, `H2`, ... — 乐句标记
- `M1`, `M2`, ... — 小节标记（对应 Score MIDI 小节号）
- 每行内容为展开后的 ABCX（不含 `::`/`:` 标记）

### 4.2 `score_structure.json`

完整的 Score 结构描述：

```json
{
  "measures": [
    {
      "measure_num": 1,
      "start_note_idx": 0,
      "end_note_idx": 12,
      "start_time": 0.0,
      "end_time": 2.0,
      "time_signature": "4/4"
    }
  ],
  "phrases": [
    {
      "phrase_id": "H1",
      "measures": [1, 2, 3, 4],
      "has_linebreak": false
    }
  ],
  "measure_to_phrase": {"1": "H1", "2": "H1", ...},
  "abcx_measures": {"1": "GA ; z2", ...},
  "midi_to_abcx": {"1": 1, "2": 2, ...},
  "midi_measure_content": {"1": "GA ; z2", ...}
}
```

### 4.3 `<perf>_refined.mid.tsv`

MIDI-TSV v0.2 格式，含乐句和小节标记：

```
# midi-tsv v0.2
# source=Aria_xxx_refined.mid
# unit=tick
# tick_scale=1
# tpq=50
# tick_ms=10
# pitch=abc-absolute
# detected_key=G
# slice_type=measure
H1	0	200
M1	0	200
C:100	0	60
g:20	15	80
...
M2	200	395
...
H2	395	590
M5	395	590
...
```

**关键约束**：
- 相邻小节时间边界连续：`M[i].end == M[i+1].start`
- 相邻乐句时间边界连续：`H[i].end == H[i+1].start`
- 乐句包含其所辖所有小节的时间范围

## 5. 执行命令

### 运行完整流程（metadata 驱动）

```bash
# 处理 Tier A（推荐，16 进程并行）
python scripts/align_score_performance.py \
    --metadata PianoCoRe/metadata.csv \
    --pianocore-root PianoCoRe \
    --output-dir PianoCoRe/aligned \
    --tier a \
    --jobs 16
```

### 处理其他 tier

```bash
# Tier A*
python scripts/align_score_performance.py \
    --metadata PianoCoRe/metadata.csv \
    --pianocore-root PianoCoRe \
    --output-dir PianoCoRe/aligned \
    --tier a_star \
    --jobs 16

# 全部 tier（不指定 --tier）
python scripts/align_score_performance.py \
    --metadata PianoCoRe/metadata.csv \
    --pianocore-root PianoCoRe \
    --output-dir PianoCoRe/aligned \
    --jobs 16
```

### 处理特定作品

```bash
python scripts/align_score_performance.py \
    --metadata PianoCoRe/metadata.csv \
    --pianocore-root PianoCoRe \
    --output-dir PianoCoRe/aligned \
    --piece-filter "Gavotte"
```

### 限制处理数量

```bash
python scripts/align_score_performance.py \
    --metadata PianoCoRe/metadata.csv \
    --pianocore-root PianoCoRe \
    --output-dir PianoCoRe/aligned \
    --limit 20
```

## 6. 验证

运行后可通过以下方式验证输出：

```bash
# 检查小节边界连续性
python scripts/align_score_performance.py \
    --metadata PianoCoRe/metadata.csv \
    --pianocore-root PianoCoRe \
    --output-dir PianoCoRe/aligned \
    --piece-filter "Gavotte"

# 查看生成的结构文件
cat PianoCoRe/aligned/Handel,_George_Frideric/Gavotte_in_G_major,_HWV_491/score_structure.json | python -m json.tool

# 检查 TSV 文件
head -30 PianoCoRe/aligned/Handel,_George_Frideric/Gavotte_in_G_major,_HWV_491/Aria_*.tsv
```

## 7. 数据覆盖与限制

### 7.1 数据覆盖统计（基于 metadata.csv）

| 类别 | 数量 | 说明 |
|------|------|------|
| metadata 总行数 | 250,046 | 全部 performance 记录 |
| Tier A（`tier_a=True`） | 157,207 performances / 1,591 pieces | note-level aligned |
| Tier A*（`tier_a_star=True`） | 130,275 performances / 1,517 pieces | note-level aligned |
| Tier B（`tier_b=True`） | 214,092 performances / 5,591 pieces | no alignment |
| Tier C（`tier_c=True`） | 250,046 performances / 5,625 pieces | no alignment |
| Tier A + 有 ABCX | ~155,956 performances / ~1,929 score files | 可生成 score-performance TSV |
| Tier A + 无 ABCX | ~1,251 performances / 7 pieces | 缺少 ABCX，无法展开结构 |

### 7.2 Score Dataset 分布

Tier A 的 1,591 pieces 来自 4 个 score dataset：

| Dataset | Score MIDI 文件名 | 说明 |
|---------|-------------------|------|
| PDMX | `score_PDMX_refined.mid` | Piano-Teach-Mix dataset |
| ASAP | `score_ASAP_refined.mid` | ASAP dataset |
| MuseScore | `score_MS_refined.mid` | MuseScore community scores |
| ATEPP | `score_ATEPP_refined.mid` | ATEPP dataset |

此外还有 mini 变体（文件名含 `_mini_`），用于简化版本处理。

### 7.3 Raw Alignment 扩展（待实现）

773 首作品有 ABCX 和 raw alignment（`<perf>_align.npz`），但当前 pipeline 只支持 refined alignment。扩展需处理：
1. raw alignment 的 `align.npz` 格式差异（字段名、索引映射方式）
2. raw score MIDI 的路径来源（`PianoCoRe/raw/` 而非 `PianoCoRe/refined/`）
3. raw performance MIDI 的路径来源
4. raw alignment 质量较低，可能需要额外的 recall/precision 过滤
