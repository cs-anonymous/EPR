# 最终脚本结构总结

## ✅ 完成的重构

### 最终脚本结构（符合真实流程）

```
scripts/
├── 01_build_score_abcx.py              # Step 1: XML/MXL → score.abcx
├── 02_build_hm_structure.py            # Step 2: 构建 H/M + 写入 aligned ABCX
├── 03_write_annotated_tsv.py           # Step 3: 写入 annotated score TSV
├── 04_project_performance_tsv.py       # Step 4: 投影到 performance TSV
└── run_pipeline.py                     # 主流程脚本
```

### 关键改进

**之前的混乱结构**：
- Step 2: 只构建 H/M 结构
- Step 3a: 写入 aligned ABCX
- Step 3b: 写入 score TSV
- Step 3c: 合并注释

**现在的清晰结构**：
- **Step 2**: 构建 H/M 结构 + 写入 aligned ABCX（紧密耦合，一起完成）
- **Step 3**: 写入 annotated score TSV（一步到位，直接生成带注释的 TSV）

### 为什么这样更好？

1. **符合真实流程**: Step 2 构建 H/M 结构后立即写入 aligned ABCX，它们是紧密耦合的
2. **减少步骤**: 从 4 个子步骤（2, 3a, 3b, 3c）简化为 2 个步骤（2, 3）
3. **更清晰**: 每个步骤的职责更明确
4. **无中间文件**: 不再生成中间的 score.mid.tsv

---

## 📋 完整数据流

```
Step 1: XML/MXL → score.abcx (σ)

Step 2: σ + score MIDI → H/M 结构 + score_aligned.abcx (σ*)
        输出: score_structure.json + score_aligned.abcx

Step 3: H/M + score MIDI + σ → score.annotated_score.mid.tsv (ψ*)
        输出: score.annotated_score.mid.tsv (带 H/M 结构和注释)

Step 4: H/M + performance MIDI + alignment → performance.mid.tsv (φ*)
        输出: performance.mid.tsv
```

---

## 🎯 符号说明（最终版）

- **σ**: score.abcx (原始 ABCX)
- **σ***: score_aligned.abcx (带 H/M 标记的对齐 ABCX)
- **ψ**: score MIDI (原始 MIDI)
- **ψ***: score.annotated_score.mid.tsv (带 H/M 结构和注释的乐谱 TSV)
- **φ**: performance MIDI (原始演奏 MIDI)
- **φ***: performance.mid.tsv (带 H/M 结构的演奏 TSV)
- **H/M**: 层次结构（H=乐句，M=小节）

**关键简化**: 不再有 ψ** 符号，ψ* 直接表示带注释的 TSV

---

## 📚 执行方式

### 完整流程
```bash
python scripts/run_pipeline.py --jobs 32
```

### 单独执行
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

# Step 4
python scripts/04_project_performance_tsv.py \
  --metadata data/performance_S_metadata.csv \
  --jobs 32
```

---

## 🔄 与旧脚本的对应关系

| 新脚本 | 旧脚本 | 说明 |
|--------|--------|------|
| `01_build_score_abcx.py` | `build_score_abcx.py` | 直接复制 |
| `02_build_hm_structure.py` | `rebuild_score_assets_from_metadata.py` (部分) | 提取 Step 2 + 添加 aligned ABCX 写入 |
| `03_write_annotated_tsv.py` | `rebuild_score_assets_from_metadata.py` (部分) + `build_annotated_score_tsv.py` | 合并 Step 3b + 3c |
| `04_project_performance_tsv.py` | `build_pianocores_miditsv.py` | 直接复制 |
| `run_pipeline.py` | `regenerate_all_pipeline.py` | 重写 |

---

## ✅ 测试状态

- ✅ Step 2 脚本已测试（1344 paired scores 成功）
- ⏳ Step 3 脚本待测试

---

## 📋 下一步

1. **测试 Step 3 脚本**（可选）
   ```bash
   python scripts/03_write_annotated_tsv.py --metadata data/score_metadata.csv --jobs 1
   ```

2. **删除旧脚本**（推荐）
   ```bash
   python scripts/cleanup_old_scripts.py
   ```

3. **更新文档**
   - 流程图需要更新（移除 Step 3a/3b/3c 的分离）
   - 文档需要反映新的 Step 2 + Step 3 结构

---

## 🎉 总结

**最终结构**: 4 个清晰的步骤脚本，符合真实的数据处理流程！

- Step 1: 转换格式
- Step 2: 构建结构 + 对齐
- Step 3: 添加注释
- Step 4: 投影到演奏

**原则**: 一个步骤一个脚本，紧密耦合的操作放在一起！
