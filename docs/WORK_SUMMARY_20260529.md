# 工作总结 - 2026-05-29

## ✅ 已完成的工作

### 1. Score-Performance Alignment Pipeline 重构

#### 数据生成
- ✅ 完整生成 129,419 个文件
- ✅ 验证新脚本输出与旧流程完全一致

#### 脚本重构
创建清晰的 4 步结构：
```
01_build_score_abcx.py          # Step 1: XML/MXL → score.abcx
02_build_hm_structure.py        # Step 2: 构建 H/M + 写入 aligned ABCX
03_write_annotated_tsv.py       # Step 3: 写入 annotated score TSV
04_project_performance_tsv.py   # Step 4: 投影到 performance TSV
run_pipeline.py                 # 主流程
```

**关键改进**：
- Step 2 包含 aligned ABCX 写入（紧密耦合的操作放在一起）
- Step 3 直接生成 annotated TSV（一步到位）
- 从 4 个子步骤简化为 2 个清晰步骤

#### 文档整合
- ✅ **主文档**: `docs/score_performance_alignment_pipeline.md`（完整流程）
- ✅ **流程图**: `docs/score_performance_alignment_tikz.pdf`
- ✅ **脚本说明**: `scripts/README.md`
- ✅ 删除 5 个冗余文档

#### 清理
- ✅ 删除 6 个旧的冗余脚本
- ✅ 保留必要的依赖脚本（如 `build_annotated_score_tsv.py`）

---

### 2. Language CPT 数据生成流程

#### 备份
- ✅ **miditsv 备份**: `data_miditsv_backup_20260529_095841.tar.gz` (578MB)

#### 脚本和文档
- ✅ **执行脚本**: `scripts/generate_language_cpt.sh`
- ✅ **完整文档**: `docs/LANGUAGE_CPT_DATA_GENERATION.md`

#### 配置
- **Tokenizer**: Qwen3.5-0.8B-LM-MIDI-Resized
- **并行度**: 32 线程
- **分批策略**: 
  - S-tier: 2 批（round1, round2）
  - A*-tier: 3 批（round3, round4, round5）
- **Token 计数**: 正则表达式 `<[^>]+>` 绕过 tokenizer

#### 数据流
```
miditsv TSV 文件
    ↓ [Step 1] build_language_cpt_measure_jsons.py
data/CorporaV2/language_cpt/
    ├── performance_Astar_midi.json
    ├── performance_S_midi.jsonl
    └── annotated_score_midi.jsonl
    ↓ [Step 2] build_language_cpt_rounds.py
data/CorporaV2/language_cpt_rounds/
    ├── round1.jsonl (S-tier 1/2)
    ├── round2.jsonl (S-tier 2/2)
    ├── round3.jsonl (A*-tier 1/3)
    ├── round4.jsonl (A*-tier 2/3)
    └── round5.jsonl (A*-tier 3/3)
```

---

## 🔄 进行中的工作

### Language CPT 数据生成
- ⏳ Step 1: 正在处理 66,450 个 A* performance 源文件
- ⏳ 使用 32 个并行进程

---

## 📚 最终文档结构

```
docs/
├── score_performance_alignment_pipeline.md    # Score-Performance 完整流程
├── score_performance_alignment_tikz.pdf       # 流程图
├── LANGUAGE_CPT_DATA_GENERATION.md            # Language CPT 数据生成
├── CPT_LANGUAGE_TRAINING.md                   # CPT 训练配置
└── LOSS_ANALYSIS.md                           # Loss 分析

scripts/
├── 01_build_score_abcx.py                     # Step 1
├── 02_build_hm_structure.py                   # Step 2
├── 03_write_annotated_tsv.py                  # Step 3
├── 04_project_performance_tsv.py              # Step 4
├── run_pipeline.py                            # Score-Performance 主流程
├── generate_language_cpt.sh                   # Language CPT 生成脚本
├── build_language_cpt_measure_jsons.py        # Language CPT Step 1
├── build_language_cpt_rounds.py               # Language CPT Step 2
└── README.md                                  # 脚本说明
```

---

## 🎯 设计原则

1. **一个步骤一个脚本** - 清晰明了
2. **紧密耦合的操作放在一起** - Step 2 包含 aligned ABCX
3. **一个文档包含所有信息** - 避免文档碎片化
4. **验证输出一致性** - 确保重构不改变结果

---

## 📊 数据统计

### Score-Performance Pipeline
- 1,600 个 score.abcx
- 7,252 个 score_structure.json + score_aligned.abcx
- 7,252 个 score.annotated_score.mid.tsv
- 129,419 个 performance.mid.tsv

### Backup
- miditsv 备份: 578MB

### Language CPT (生成中)
- 预计输出: 5 个 round JSONL 文件
- 数据源: 66,450 个 A* + 62,969 个 S + 7,252 个 annotated scores

---

## 🔧 技术亮点

### Score-Performance Pipeline
1. **H/M 层次结构**: 乐句（H）和小节（M）的两层结构
2. **对齐算法**: 基于 NPZ 对齐数据的时间戳映射
3. **注释提取**: 从 ABCX XML 提取力度、演奏法、表情等

### Language CPT
1. **快速 Token 计数**: 正则表达式绕过 tokenizer，性能提升显著
2. **小节边界切分**: 在 M 标记处切分，保持音乐结构完整
3. **多轮训练策略**: 分批训练，避免过拟合

---

## 📝 待办事项

- ⏳ 等待 Language CPT Step 1 完成
- ⏳ 执行 Language CPT Step 2
- ⏳ 验证生成的数据

---

## 🎉 总结

**今日完成**：
1. ✅ Score-Performance Pipeline 完整重构和验证
2. ✅ 文档整合和清理
3. ✅ Language CPT 流程文档化
4. ✅ miditsv 数据备份
5. ⏳ Language CPT 数据生成（进行中）

**成果**：
- 清晰的脚本结构
- 完整的文档
- 验证过的数据生成流程
- 自动化的执行脚本
