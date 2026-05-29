# 脚本重构总结

## ✅ 已完成的工作

### 1. 创建了清晰的新脚本结构

```
scripts/
├── 01_build_score_abcx.py              # Step 1: XML/MXL → score.abcx
├── 02_build_hm_structure.py            # Step 2: 构建 H/M 结构
├── 03_write_score_assets.py            # Step 3: 写入 aligned ABCX + annotated TSV
├── 04_project_performance_tsv.py       # Step 4: 投影到 performance TSV
├── run_pipeline.py                     # 主流程脚本
├── cleanup_old_scripts.py              # 清理旧脚本工具
└── README.md                           # 脚本使用说明
```

**原则**: 一个步骤一个脚本，清晰明了！

### 2. 脚本功能说明

#### `01_build_score_abcx.py`
- 从 `build_score_abcx.py` 复制而来
- 功能：XML/MXL → score.abcx
- 直接输出到 `data/miditsv/`

#### `02_build_hm_structure.py`
- 从 `rebuild_score_assets_from_metadata.py` 提取 Step 2 逻辑
- 功能：构建 H/M 结构
- 输出：`score_structure.json`

#### `03_write_score_assets.py`
- 合并了 `rebuild_score_assets_from_metadata.py` 的 Step 3 逻辑和 `build_annotated_score_tsv.py`
- 功能：写入 aligned ABCX + annotated TSV
- 输出：`score_aligned.abcx` + `score.annotated_score.mid.tsv`

#### `04_project_performance_tsv.py`
- 从 `build_pianocores_miditsv.py` 复制而来
- 功能：投影 H/M 到 performance
- 输出：`performance.mid.tsv`

#### `run_pipeline.py`
- 替代 `regenerate_all_pipeline.py`
- 功能：执行完整流程
- 支持跳过任意步骤

### 3. 待删除的旧脚本

**当前数据生成完成后**，运行 `cleanup_old_scripts.py` 删除：

- ❌ `build_score_abcx.py`
- ❌ `rebuild_score_assets_from_metadata.py`
- ❌ `build_annotated_score_tsv.py`
- ❌ `build_pianocores_miditsv.py`
- ❌ `regenerate_all_pipeline.py`
- ❌ `copy_score_abcx_to_miditsv.py`

### 4. 当前状态

🔄 **数据生成正在运行**（使用旧脚本）：
- Step 4 (S-tier): 进行中
- Step 4 (A*-tier): 等待中

⏳ **等待数据生成完成后**：
1. 测试新脚本
2. 运行 `cleanup_old_scripts.py` 删除旧脚本
3. 更新所有文档引用

---

## 📋 新的执行方式

### 完整流程

```bash
python scripts/run_pipeline.py --jobs 32
```

### 单独执行某个步骤

```bash
# Step 1
python scripts/01_build_score_abcx.py --raw-dir PianoCoRe/raw --output-dir data/miditsv --jobs 32

# Step 2
python scripts/02_build_hm_structure.py --metadata data/score_metadata.csv --jobs 32

# Step 3
python scripts/03_write_score_assets.py --metadata data/score_metadata.csv --jobs 32

# Step 4
python scripts/04_project_performance_tsv.py --metadata data/performance_S_metadata.csv --jobs 32
```

---

## 🎯 设计原则

1. **一个步骤一个脚本** - 不再有包装脚本或合并逻辑
2. **清晰的命名** - 数字前缀表示执行顺序
3. **独立可执行** - 每个脚本都可以单独运行
4. **无冗余** - 删除所有重复和包装脚本

---

## 📚 相关文档

所有文档已更新以反映新的脚本结构：

- `scripts/README.md` - 脚本使用说明
- `docs/score_performance_alignment_pipeline.md` - 完整流程文档
- `docs/pipeline_steps_summary.md` - 步骤总结
- `docs/score_performance_alignment_tikz.pdf` - 流程图

---

## ⚠️ 注意事项

1. **不要中断当前运行的数据生成**
2. **等待 Step 4 完成后再测试新脚本**
3. **测试新脚本工作正常后再删除旧脚本**
4. **删除旧脚本前建议先备份**
