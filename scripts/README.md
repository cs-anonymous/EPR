# Pipeline Scripts

清晰的数据生成流程脚本，一个步骤一个脚本。

---

## 主流程脚本

```bash
python scripts/run_pipeline.py --jobs 32
```

执行完整的数据生成流程（Step 1-4）。

**选项**：
- `--jobs N`: 并行进程数（默认：32）
- `--skip-step1`: 跳过 Step 1
- `--skip-step2`: 跳过 Step 2
- `--skip-step3`: 跳过 Step 3
- `--skip-step4-s`: 跳过 Step 4 (S-tier)
- `--skip-step4-astar`: 跳过 Step 4 (A*-tier)

---

## 独立步骤脚本

### Step 1: 构建 score.abcx

```bash
python scripts/01_build_score_abcx.py \
  --raw-dir PianoCoRe/raw \
  --output-dir data/miditsv \
  --jobs 32 \
  --force
```

**输入**: `PianoCoRe/raw/Composer/Piece/score.mxl`  
**输出**: `data/miditsv/Composer/Piece/score.abcx`

从 XML/MXL 转换生成 ABCX 格式。

---

### Step 2: 构建 H/M 结构 + 写入 aligned ABCX

```bash
python scripts/02_build_hm_structure.py \
  --metadata data/score_metadata.csv \
  --pianocore-root PianoCoRe \
  --jobs 32
```

**输入**:
- `data/miditsv/Composer/Piece/score.abcx`
- `PianoCoRe/raw/Composer/Piece/score_*.mid`

**输出**: 
- `data/miditsv/Composer/Piece/score_structure.json`
- `data/miditsv/Composer/Piece/score_aligned.abcx`

从 score MIDI 提取小节网格，将 ABCX 内容映射到 MIDI 小节，分组为乐句（H）和小节（M），并写入带 H/M 标记的 aligned ABCX。

---

### Step 3: 写入 annotated score TSV

```bash
python scripts/03_write_annotated_tsv.py \
  --metadata data/score_metadata.csv \
  --pianocore-root PianoCoRe \
  --jobs 32
```

**输入**:
- `data/miditsv/Composer/Piece/score_structure.json`
- `PianoCoRe/raw/Composer/Piece/score_*.mid`
- `data/miditsv/Composer/Piece/score.abcx` (含注释)

**输出**: `data/miditsv/Composer/Piece/score.annotated_score.mid.tsv`

生成带 H/M 结构和注释的乐谱 TSV。

---

### Step 4: 投影到 performance TSV

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

**输入**:
- `data/miditsv/Composer/Piece/score_structure.json`
- `PianoCoRe/refined/Composer/Piece/performance_refined.mid`
- `PianoCoRe/refined/Composer/Piece/performance_refined_align.npz`

**输出**: `data/miditsv/Composer/Piece/performance_refined.mid.tsv`

通过对齐数据将 H/M 结构投影到演奏 MIDI。

---

## 脚本结构

```
scripts/
├── 01_build_score_abcx.py          # Step 1: XML/MXL → score.abcx
├── 02_build_hm_structure.py        # Step 2: 构建 H/M + 写入 aligned ABCX
├── 03_write_annotated_tsv.py       # Step 3: 写入 annotated score TSV
├── 04_project_performance_tsv.py   # Step 4: 投影到 performance TSV
├── run_pipeline.py                 # 主流程脚本
└── cleanup_old_scripts.py          # 清理旧脚本工具
```

---

## 数据流

```
Step 1: XML/MXL → score.abcx (σ)
Step 2: σ + score MIDI → H/M 结构 + score_aligned.abcx (σ*)
Step 3: H/M + score MIDI + σ → score.annotated_score.mid.tsv (ψ*)
Step 4: H/M + performance MIDI + alignment → performance.mid.tsv (φ*)
```

---

## 清理旧脚本

等待数据生成完成后，运行清理脚本删除旧的冗余脚本：

```bash
python scripts/cleanup_old_scripts.py
```

将删除以下旧脚本：
- `build_score_abcx.py`
- `rebuild_score_assets_from_metadata.py`
- `build_annotated_score_tsv.py`
- `build_pianocores_miditsv.py`
- `regenerate_all_pipeline.py`
- `copy_score_abcx_to_miditsv.py`

---

## 相关文档

- **完整流程文档**: `docs/score_performance_alignment_pipeline.md`
- **流程图**: `docs/score_performance_alignment_tikz.pdf`
