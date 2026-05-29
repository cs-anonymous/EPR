# 完整数据生成流程总结

## 执行命令

使用32线程重新生成所有数据：

```bash
python scripts/regenerate_all_pipeline.py --jobs 32
```

## 流程步骤

### ✅ Step 1: 生成 score.abcx (1600/1607 成功)
- **输入**: `PianoCoRe/raw/Composer/Piece/score.mxl`
- **输出**: `data/miditsv/Composer/Piece/score.abcx`
- **脚本**: `scripts/build_score_abcx.py`
- **说明**: 直接从 XML/MXL 转换生成 ABCX 到最终输出目录
- **耗时**: ~1分钟（32线程）

### ✅ Step 2-3: 生成对齐数据 (7252 成功)
- **输入**: 
  - `data/miditsv/Composer/Piece/score.abcx` (来自 Step 1)
  - `PianoCoRe/raw/Composer/Piece/score_*.mid`
- **输出**:
  - `data/miditsv/Composer/Piece/score_aligned.abcx` (带 H/M 标记)
  - `data/miditsv/Composer/Piece/score_structure.json` (层次结构)
  - `data/miditsv/Composer/Piece/score.mid.tsv` (乐谱 MIDI TSV)
- **脚本**: `scripts/rebuild_score_assets_from_metadata.py`
- **耗时**: ~2分钟（32线程）

### 🔄 Step 3.5: 生成带注释的乐谱 TSV (进行中)
- **输入**:
  - `data/miditsv/Composer/Piece/score.abcx` (含注释)
  - `data/miditsv/Composer/Piece/score.mid.tsv`
- **输出**:
  - `data/miditsv/Composer/Piece/score.annotated_score.mid.tsv`
- **脚本**: `scripts/build_annotated_score_tsv.py`
- **注释类型**:
  - 力度: pppp, ppp, pp, p, mp, mf, f, ff, fff, ffff
  - 演奏法: accent, staccato, tenuto, sfz
  - 装饰音: arpeggio, turn, trill
  - 范围标记: crescendo, diminuendo
  - 踏板: down, up
  - 表情术语: a_tempo, dolce, rit, rall 等

### 🔄 Step 4a: 生成 S-tier 演奏 TSV (388/1587, 24%)
- **输入**:
  - `data/miditsv/Composer/Piece/score_structure.json`
  - `PianoCoRe/refined/Composer/Piece/performance_refined.mid`
  - `PianoCoRe/refined/Composer/Piece/performance_refined_align.npz`
- **输出**:
  - `data/miditsv/Composer/Piece/performance_refined.mid.tsv`
- **脚本**: `scripts/build_pianocores_miditsv.py`
- **数据量**: 1587 scores, 62969 performances

### ⏳ Step 4b: 生成 A*-tier 演奏 TSV (等待中)
- **脚本**: `scripts/process_astar_performances.py`
- **数据量**: A*-tier 高质量子集

## 输出文件结构

```
data/miditsv/
└── Composer/
    └── Piece/
        ├── score.abcx                          # 源 ABCX
        ├── score_aligned.abcx                  # 对齐后的 ABCX (带 H/M)
        ├── score_structure.json                # H/M 层次结构
        ├── score.mid.tsv                       # 乐谱 MIDI TSV
        ├── score.annotated_score.mid.tsv       # 带注释的乐谱 TSV
        ├── performance_1.mid.tsv               # 演奏 1 TSV
        ├── performance_2.mid.tsv               # 演奏 2 TSV
        └── piece_interpretation.json           # 作品元数据
```

## TSV 格式示例

### score.mid.tsv (基础乐谱)
```
H 0 0 1940
M 0 0 480
G3 80 480 0
A3 75 240 0
```

### score.annotated_score.mid.tsv (带注释)
```
H 0 0 1940
M 0 0 480
dynamic p
G3 80 480 0
accent
A3 75 240 0
pedal down
```

### performance.mid.tsv (演奏)
```
H 0 0 2260
M 0 0 520
G3 71 495 0
A3 64 235 0
pedal down
```

## 数据统计

- **总乐谱数**: 7252
  - Paired (有 MIDI): 1344
  - Orphan (仅 ABCX): 5908
- **S-tier 演奏**: 62969 个
- **A*-tier 演奏**: 高质量子集
- **对齐质量**: 中位数 recall >95%

## 并行处理

所有步骤使用 32 个并行进程，充分利用多核 CPU：
- Step 1: 32 workers
- Step 2-3: 32 workers  
- Step 3.5: 32 workers
- Step 4a: 32 workers
- Step 4b: 32 workers

## 相关文档

- **完整文档**: `docs/score_performance_alignment_pipeline.md`
- **流程图**: `docs/score_performance_alignment_tikz.tex`
- **主脚本**: `scripts/regenerate_all_pipeline.py`
