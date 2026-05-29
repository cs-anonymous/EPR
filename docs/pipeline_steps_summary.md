# 数据生成流程总结

## 当前状态

✅ **Step 1**: 生成 score.abcx (σ) - 1600/1607 成功  
✅ **Step 2**: 构建 H/M 结构 - 7252 成功  
✅ **Step 3a**: 生成 score_aligned.abcx (σ*) - 7252 成功  
✅ **Step 3b**: 生成 score.mid.tsv (ψ*) - 7252 成功  
✅ **Step 3c**: 生成 score.annotated_score.mid.tsv (ψ**) - 7252 成功  
🔄 **Step 4**: 投影到 performance TSV (φ*) - S-tier: 432/1587 (27%)  
⏳ **Step 4**: 投影到 performance TSV (φ*) - A*-tier: 等待中

---

## 完整流程说明

### Step 1: 构建原始 ABCX (σ₀ → σ)

**输入**: `PianoCoRe/raw/Composer/Piece/score.mxl`  
**输出**: `data/miditsv/Composer/Piece/score.abcx`  
**脚本**: `scripts/build_score_abcx.py`

从 XML/MXL 转换生成 ABCX 格式，直接输出到最终目录。

```bash
python scripts/build_score_abcx.py \
  --raw-dir PianoCoRe/raw \
  --output-dir data/miditsv \
  --jobs 32 \
  --force
```

---

### Step 2: 构建 H/M 结构 (σ + ψ → H/M)

**输入**:
- `data/miditsv/Composer/Piece/score.abcx` (σ)
- `PianoCoRe/raw/Composer/Piece/score_*.mid` (ψ)

**输出**: H/M 结构（内存中，供 Step 3 使用）

**脚本**: `scripts/rebuild_score_assets_from_metadata.py` (内部步骤)

从 score MIDI 提取小节网格，将 ABCX 内容映射到 MIDI 小节，分组为乐句。

---

### Step 3a: 写入对齐的 ABCX (H/M + σ → σ*)

**输入**: 
- H/M 结构（来自 Step 2）
- `data/miditsv/Composer/Piece/score.abcx` (σ)

**输出**:
- `data/miditsv/Composer/Piece/score_aligned.abcx` (σ*)
- `data/miditsv/Composer/Piece/score_structure.json`

**脚本**: `scripts/rebuild_score_assets_from_metadata.py`

在 ABCX 中插入 H/M 结构标记：
- `<H><V000>` - 乐句标记
- `<M><V000>` - 小节标记

---

### Step 3b: 写入带注释的乐谱 TSV (ψ + σ → ψ*)

**输入**:
- H/M 结构（来自 Step 2）
- `PianoCoRe/raw/Composer/Piece/score_*.mid` (ψ)
- `data/miditsv/Composer/Piece/score.abcx` (σ, 含注释)

**输出**: `data/miditsv/Composer/Piece/score.annotated_score.mid.tsv` (ψ*)

**脚本**: `scripts/03_write_score_assets.py`

生成带 H/M 结构和注释的乐谱 TSV：

1. **标记化 MIDI 事件**:
   - 音符: pitch, velocity, duration, voice
   - 踏板事件
   - 时间签名

2. **添加结构标记**:
   - H 行: `H phrase_id start_tick duration_tick`
   - M 行: `M measure_id start_tick duration_tick`

3. **合并注释**:
   - 从 ABCX 提取注释（力度、演奏法、表情等）
   - 插入到对应位置

```bash
python scripts/03_write_score_assets.py \
  --metadata data/score_metadata.csv \
  --pianocore-root PianoCoRe \
  --jobs 32
```

**注释类型**:
- 力度: pppp, ppp, pp, p, mp, mf, f, ff, fff, ffff
- 演奏法: accent, staccato, tenuto, sfz
- 装饰音: arpeggio, turn, trill
- 范围: crescendo, diminuendo
- 踏板: down, up
- 表情: a_tempo, dolce, rit, rall 等

**TSV 格式**:
```
H 0 0 1940
M 0 0 480
dynamic p
G3 80 480 0
accent
A3 75 240 0
```

---

### Step 4: 投影 H/M 到演奏 (H/M + φ → φ*)

**输入**:
- `data/miditsv/Composer/Piece/score_structure.json` (H/M)
- `PianoCoRe/refined/Composer/Piece/performance_refined.mid` (φ)
- `PianoCoRe/refined/Composer/Piece/performance_refined_align.npz` (对齐)

**输出**: `data/miditsv/Composer/Piece/performance_refined.mid.tsv` (φ*)

**脚本**:
- S-tier: `scripts/build_pianocores_miditsv.py`
- A*-tier: `scripts/process_astar_performances.py`

通过对齐数据将 H/M 结构投影到演奏 MIDI。

```bash
# S-tier
python scripts/build_pianocores_miditsv.py \
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

**TSV 格式**:
```
H 0 0 2260
M 0 0 520
G3 71 495 0
A3 64 235 0
pedal down
```

---

## 符号说明

- **σ₀**: 原始 XML/MXL
- **σ**: score.abcx (原始 ABCX)
- **σ***: score_aligned.abcx (带 H/M 标记的对齐 ABCX)
- **ψ**: score MIDI (原始 MIDI)
- **ψ***: score.annotated_score.mid.tsv (带 H/M 结构和注释的乐谱 TSV)
- **φ**: performance MIDI (原始演奏 MIDI)
- **φ***: performance.mid.tsv (带 H/M 结构的演奏 TSV)
- **H/M**: 层次结构（H=乐句，M=小节）

---

## 数据流图

```
σ₀ (XML/MXL) ──[1]──> σ (score.abcx)
                       │
                       │ [2] + ψ (score MIDI)
                       ↓
                    H/M 结构
                       │
        ┌──────────────┼──────────────┐
        │              │              │
      [3a]           [3b]             │
        ↓              ↓              │
   σ* (aligned)   ψ* (annotated TSV) │
                  (含 H/M + 注释)     │
                  
φ (performance MIDI) + H/M ──[4]──> φ* (performance TSV)
```

---

## 输出文件结构

```
data/miditsv/
└── Composer/
    └── Piece/
        ├── score.abcx                          # σ (原始)
        ├── score_aligned.abcx                  # σ* (对齐)
        ├── score_structure.json                # H/M 结构
        ├── score.mid.tsv                       # ψ* (乐谱 TSV)
        ├── score.annotated_score.mid.tsv       # ψ** (带注释)
        ├── performance_1.mid.tsv               # φ* (演奏 1)
        ├── performance_2.mid.tsv               # φ* (演奏 2)
        └── piece_interpretation.json           # 元数据
```

---

## 执行完整流程

```bash
python scripts/regenerate_all_pipeline.py --jobs 32
```

**选项**:
- `--skip-score-abcx`: 跳过 Step 1
- `--skip-score-assets`: 跳过 Step 2-3c
- `--skip-performance-s`: 跳过 Step 4 (S-tier)
- `--skip-performance-astar`: 跳过 Step 4 (A*-tier)

---

## 相关文档

- **完整文档**: `docs/score_performance_alignment_pipeline.md`
- **流程图**: `docs/score_performance_alignment_tikz.tex`
- **主脚本**: `scripts/regenerate_all_pipeline.py`
