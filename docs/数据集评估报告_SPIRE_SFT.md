# 数据集评估报告：SPIRE SFT 设计 2.4 节三类数据集支撑能力

## 评估日期
2026-05-09

## 评估目标
检查现有 **PianoCoRe 数据集** 和 **score_processed 数据集** 是否能支撑 SPIRE SFT 设计.md 2.4 节中定义的三类数据集：

1. **未配对乐谱集** $\mathcal{D}_{\Sigma}$：仅有 score，无对应 performance
2. **未配对演奏集** $\mathcal{D}_{\Phi}$：仅有 performance MIDI，无对应 score
3. **小节级配对集** $\mathcal{D}_{\Sigma\Phi}^{M}$：score-performance 在 measure 级别对齐

---

## 一、数据集概览

### 1.1 PianoCoRe 数据集

**PianoCoRe 1.0** 是一个大规模的钢琴 score-performance 配对数据集，整合了多个来源：

**Score 数据来源**：
- PDMX: 60,186 个
- ASAP: 55,171 个
- MuseScore: 44,576 个
- ATEPP: 28,486 个

**Performance 数据来源**：
- Aria-MIDI: 200,504 个
- PERiScoPe: 34,773 个
- ATEPP: 11,564 个
- GiantMIDI-Piano: 2,139 个
- ASAP: 1,066 个

### 1.2 score_processed 数据集

**独立的未配对乐谱集**，用于补充 Score Language 训练数据：

| 数据源 | 文件数 | 格式 | 说明 |
|--------|--------|------|------|
| **PDMX** | 2,941 | ABCX | 从 PDMX 数据库转换的乐谱 |
| **OpenScore_Lieder** | 1,345 | ABCX | 艺术歌曲乐谱集 |
| **DCMLab** | 343 | ABCX | 和声分析语料库 |
| **KernScores_sonatas** | 191 | ABCX | 奏鸣曲乐谱集 |
| **总计** | **4,820** | ABCX | 全部已转换为 ABCX 格式 |

---

## 二、三类数据集统计

### 2.1 PianoCoRe 数据分布

| 数据类型 | 数量 | 占比 | 说明 |
|---------|------|------|------|
| **总记录数** | 250,046 | 100% | PianoCoRe 1.0 完整数据集 |
| **音符级配对数据** | 188,419 | 75.4% | 有 score + performance + alignment |
| **未配对乐谱集** | 0 | 0% | PianoCoRe 中无独立的未配对乐谱 |
| **未配对演奏集** | 61,627 | 24.6% | 仅有 performance，无 score |

**重要发现**：
- PianoCoRe 提供了 **188,419 对音符级配对数据**，其中 **97.8% (184,230 对) 已经过 refined 处理**
- PianoCoRe 中的 score 都有对应的 performance（即没有独立的未配对乐谱）
- 未配对演奏集数量充足（61,627 个），主要来自 Aria-MIDI (51,270) 和 PERiScoPe (5,672)

### 2.2 配对数据质量分布

| 质量等级 | 数量 | 占比 | 标准 |
|---------|------|------|------|
| **Excellent** | 181,040 | 96.1% | recall > 0.9, precision > 0.85 |
| **High** | 0 | 0% | recall > 0.85, precision > 0.75 |
| **Medium** | 2 | 0% | recall > 0.75, precision > 0.65 |
| **Low** | 7,377 | 3.9% | 其他 |
| **可用于 EPR/CSR** | 181,040 | **96.1%** | Excellent + High |

**结论**：PianoCoRe 的配对数据质量极高，96.1% 的数据可直接用于 EPR/CSR 训练。

### 2.3 PianoCoRe Tier 分布

| Tier | 总数 | 配对数据 | 说明 |
|------|------|---------|------|
| **Tier B** | 2 | 2 | 最高质量，人工验证 |
| **Tier A** | 12,205 | 7,888 | 高质量，自动筛选 |

---

## 三、三类数据集支撑能力评估

### 3.1 未配对乐谱集 $\mathcal{D}_{\Sigma}$ ✅ **充足**

**数据来源**：
1. **PianoCoRe 未配对乐谱**：0 个（PianoCoRe 中的 score 都有对应 performance）
2. **score_processed**：4,820 个 ABCX 文件（独立补充）
3. **总计**：**4,820 个未配对乐谱**

**用途**（设计文档 4.1 节）：
- Score Language SFT：phrase/measure continuation
- Score mask reconstruction（$f$-mask）：遮去 acc/treble/bass/label 等属性

**格式支持**：
- score_processed：ABCX（已处理好的统一格式）

**评估结论**：✅ **充足**
- 4,820 个未配对乐谱可以支撑 Score Language Learning
- ABCX 格式统一，便于批量处理
- 覆盖多种风格：古典奏鸣曲（KernScores）、艺术歌曲（OpenScore_Lieder）、和声分析语料（DCMLab）、PDMX 数据库
- **可选扩展**：PianoCoRe 中的 188,419 个配对 score 也可以用于 Score Language 训练（忽略 performance）

---

### 3.2 未配对演奏集 $\mathcal{D}_{\Phi}$ ✅ **充足**

**数据来源**：
- **PianoCoRe 未配对演奏**：61,627 个 performance MIDI
  - Aria-MIDI: 51,270 个
  - PERiScoPe: 5,672 个
  - ATEPP: 2,800 个
  - GiantMIDI-Piano: 1,884 个
  - ASAP: 1 个

**用途**（设计文档 4.2 节）：
- Performance Language SFT：phrase/measure continuation
- Performance mask reconstruction（$g$-mask）：遮去 timing/velocity/duration/pedal 等属性

**处理需求**：
- 使用 **Omnizart** 算法识别 downbeat
- 根据 downbeat 切割成小节 $\phi_{M_k}$
- 启发式算法连接成乐句 $\phi_{H_k}$

**评估结论**：✅ **充足**
- 61,627 个未配对演奏数量充足
- 数量是未配对乐谱的 **12.8 倍**，完全符合设计文档中 Performance Language 占比更高的要求（40-50% vs 25-35%）
- 主要来自 Aria-MIDI（自动转录）和 PERiScoPe（真实演奏）
- 需要实现 Omnizart downbeat 检测 + 启发式乐句切分
- **可选扩展**：PianoCoRe 中的 188,419 个配对 performance 也可以用于 Performance Language 训练（忽略 score）

---

### 3.3 小节级配对集 $\mathcal{D}_{\Sigma\Phi}^{M}$ ✅ **充足且高质量**

**数据来源**：
- **PianoCoRe 音符级配对数据**：188,419 对
- **高质量配对数据**：181,040 对（96.1%）
- **Refined 数据**：184,230 对（97.8%）

**用途**（设计文档 4.3 节）：
- EPR Branch：完整 EPR rendering、EPR attribute generation（$g$-mask）
- CSR Branch：CSR head prediction、Head-conditioned CSR、CSR attribute recovery（$f$-mask）

**处理需求**：
- ⚠️ **关键问题**：PianoCoRe 提供的是 **音符级配对**（note-level alignment），需要处理成 **小节级配对**（measure-level alignment）
- 需要实现：
  1. 从 alignment 文件（.npz）中提取音符级对齐信息
  2. 根据 score 的小节边界，将 performance 也切割成对应小节
  3. 启发式算法将小节连接成乐句（4-8 measures）
  4. 配对质量控制：如果 phrase 级对齐质量差，降级为未配对数据

**评估结论**：✅ **充足且高质量**
- 188,419 对音符级配对数据量充足
- 96.1% 的数据质量达到 Excellent 级别（recall > 0.9, precision > 0.85）
- 97.8% 的数据已经过 refined 处理，对齐质量有保障
- **需要开发**：音符级对齐 → 小节级对齐的转换工具

---

## 四、数据处理流程建议

### 4.1 未配对乐谱集处理

```python
# 输入：
# - score_processed/**/*.abcx 文件（4,820 个）
# - （可选）PianoCoRe 中的 188,419 个配对 score（忽略 performance）

# 输出：
# - 乐句级 ABCX 文件：{source}/{composer}/{piece}/score_phrase_{k}.abcx
# - 小节级 ABCX 文件：{source}/{composer}/{piece}/score_measure_{k}.abcx

# 步骤：
1. 读取 ABCX 文件
2. 启发式切割成乐句（4-8 measures）
3. 提取 head 信息（调号、拍号、tempo、metadata）
4. 生成 Score Language 训练样本
```

### 4.2 未配对演奏集处理

```python
# 输入：
# - PianoCoRe/metadata.csv 中 performance_midi_path 非空但 score_xml_path 为空的记录（61,627 个）
# - （可选）PianoCoRe 中的 188,419 个配对 performance（忽略 score）

# 输出：
# - 乐句级 MIDI-TSV 文件：{source}/{id}/perf_phrase_{k}.tsv
# - 小节级 MIDI-TSV 文件：{source}/{id}/perf_measure_{k}.tsv

# 步骤：
1. 读取 performance MIDI 文件
2. 使用 Omnizart 识别 downbeat
3. 根据 downbeat 切割成小节 φ_M_k
4. 启发式算法连接成乐句 φ_H_k（如果质量不佳，降级为 measure 级别）
5. 生成 Performance Language 训练样本
```

### 4.3 小节级配对集处理 ⚠️ **需要重点开发**

```python
# 输入：
# - PianoCoRe/metadata.csv 中同时有 score_xml_path、performance_midi_path、raw_alignment_path 的记录
# - 优先使用 refined_alignment_path（97.8% 的数据有）

# 输出：
# - 乐句级配对：{composer}/{piece}/pair_phrase_{k}.json
#   {
#     "score_phrase": "...",  # ABCX 格式
#     "perf_phrase": "...",   # MIDI-TSV 格式
#     "alignment_quality": {"recall": 0.95, "precision": 0.92}
#   }

# 步骤：
1. 读取 score MusicXML 和 performance MIDI
2. 读取 alignment 文件（.npz），提取音符级对齐信息
3. 根据 score 的小节边界，将 performance 也切割成对应小节
4. 启发式算法将小节连接成乐句（4-8 measures）
5. 配对质量控制：
   - 检查 measure 数量是否匹配
   - 检查边界偏移是否过大
   - 如果质量差，降级为未配对数据
6. 生成 EPR/CSR 训练样本
```

---

## 五、潜在问题与解决方案

### 4.1 音符级对齐 → 小节级对齐转换

**问题**：PianoCoRe 提供的是音符级对齐（note-level），需要转换为小节级对齐（measure-level）。

**解决方案**：
1. 读取 alignment .npz 文件，提取 `score_to_performance` 映射
2. 根据 score 的 measure 边界（从 MusicXML 中提取），将 performance notes 分组到对应小节
3. 检查每个小节的对齐质量：
   - 计算小节内的 recall 和 precision
   - 如果某个小节的对齐质量低于阈值（如 recall < 0.75），标记为低质量
4. 连接小节成乐句时，跳过低质量小节或降级为未配对数据

### 4.2 Performance 时间归一化

**问题**：设计文档 4.4 节要求 "目标小节内部的时间写成相对 measure onset，而非全曲绝对 tick"。

**解决方案**：
1. 识别每个小节的起始时间（measure onset）
2. 将小节内所有 note 的 onset 时间减去 measure onset
3. 生成 MIDI-TSV 时，使用相对时间而非绝对时间

### 4.3 Phrase 切分质量控制

**问题**：启发式算法切分的 phrase 可能质量不佳（如边界不自然、长度不均）。

**解决方案**：
1. 优先使用 score 的结构信息（repeat、section、phrase mark）
2. 如果没有结构信息，使用启发式规则：
   - 默认 4-8 measures 为一个 phrase
   - 在 rest、fermata、tempo change 处切分
   - 避免在 tie、slur 中间切分
3. 对于长乐句（> 8 measures），加入 intra-phrase continuation 任务

### 4.4 数据采样上限

**问题**：设计文档 4.4 节要求 "同一首曲子限制采样 K 个 windows（如 20-50 个），避免长曲子支配训练集"。

**解决方案**：
1. 统计每首曲子的 phrase 数量
2. 如果 phrase 数量 > K，随机采样 K 个 phrase
3. 确保训练集中曲目分布均衡

---

## 六、总结与建议

### 6.1 数据集支撑能力总结

| 数据集类型 | 需求量 | 现有量 | 质量 | 支撑能力 |
|-----------|--------|--------|------|---------|
| **未配对乐谱集** $\mathcal{D}_{\Sigma}$ | 中等 | 4,820 (+188k 可选) | 高 | ✅ **充足** |
| **未配对演奏集** $\mathcal{D}_{\Phi}$ | 高 | 61,627 (+188k 可选) | 高 | ✅ **充足** |
| **小节级配对集** $\mathcal{D}_{\Sigma\Phi}^{M}$ | 高 | 188,419 对（音符级） | 极高（96.1% excellent） | ✅ **充足且高质量** |

**说明**：
- 未配对乐谱集：score_processed 提供 4,820 个独立乐谱，PianoCoRe 的 188k 配对 score 可作为补充
- 未配对演奏集：PianoCoRe 提供 61,627 个独立演奏，188k 配对 performance 可作为补充
- 小节级配对集：PianoCoRe 提供 188,419 对音符级配对，需转换为小节级

### 6.2 关键结论

1. ✅ **数据量充足**：三类数据集的数量都能满足 SPIRE SFT 训练需求
2. ✅ **质量优秀**：配对数据 96.1% 达到 Excellent 级别，97.8% 经过 refined 处理
3. ✅ **格式统一**：score_processed 已全部转换为 ABCX 格式，便于处理
4. ✅ **比例合理**：未配对演奏集（61k）远多于未配对乐谱集（4.8k），符合设计文档中 Performance Language 占比更高的要求
5. ⚠️ **需要开发**：音符级对齐 → 小节级对齐的转换工具是关键

### 6.3 数据扩展策略

**如果 4,820 个未配对乐谱不够用**，可以采用以下策略：
1. **使用配对数据的 score**：PianoCoRe 的 188,419 个配对 score 可以忽略 performance，用于 Score Language 训练
2. **使用配对数据的 performance**：PianoCoRe 的 188,419 个配对 performance 可以忽略 score，用于 Performance Language 训练
3. **优势**：这样可以大幅增加 Language Learning 阶段的数据量，提升模型对 ABCX 和 MIDI-TSV 格式的熟悉度

### 6.4 下一步工作建议

**优先级 1（必须）**：
1. 开发 **音符级对齐 → 小节级对齐** 转换工具
2. 实现 **Omnizart downbeat 检测** + 启发式乐句切分
3. 实现 **配对质量控制**：检查 measure 匹配度、边界偏移

**优先级 2（重要）**：
1. 实现 **Performance 时间归一化**（相对 measure onset）
2. 实现 **Phrase 切分质量控制**（基于结构信息 + 启发式规则）
3. 实现 **数据采样上限**（每首曲子最多 K 个 windows）

**优先级 3（优化）**：
1. 统计数据集的风格分布（巴洛克、古典、浪漫派等）
2. 分析数据集的难度分布（音符密度、和声复杂度等）
3. 构建数据集的元信息索引（composer、piece、duration、note_count 等）

### 6.5 风险提示

1. **音符级 → 小节级转换的准确性**：这是整个流程的关键，需要充分测试
2. **Phrase 切分的一致性**：启发式算法可能在不同曲目上表现不一致
3. **未配对乐谱集数量相对较少**：4,820 个可能不够，建议使用配对数据的 score 作为补充（忽略 performance）
4. **数据不平衡**：未配对演奏集（61k）远多于未配对乐谱集（4.8k），但这符合设计文档的要求

---

## 七、附录：数据集文件结构

### 7.1 PianoCoRe 文件结构

```
PianoCoRe/
├── metadata.csv                          # 主索引文件
├── PianoCoRe-1.0-raw-midi.zip           # 原始 MIDI 文件
├── PianoCoRe-1.0-raw-alignments.zip     # 原始对齐文件
└── PianoCoRe-1.0-refined.zip            # Refined 数据（97.8% 的配对数据）
```

### 7.2 score_processed 文件结构

```
score_processed/
├── PDMX/                    # 2,941 个 ABCX 文件
│   └── {id}/{id}.abcx
├── OpenScore_Lieder/        # 1,345 个 ABCX 文件
├── DCMLab/                  # 343 个 ABCX 文件
└── KernScores_sonatas/      # 191 个 ABCX 文件
    └── {composer}-{piece}.abcx
```

### 7.3 建议的输出文件结构

```
sft_data/
├── score_language/          # 未配对乐谱集
│   ├── phrase/              # 乐句级
│   │   └── {id}_phrase_{k}.abcx
│   └── measure/             # 小节级
│       └── {id}_measure_{k}.abcx
├── performance_language/    # 未配对演奏集
│   ├── phrase/              # 乐句级
│   │   └── {id}_phrase_{k}.tsv
│   └── measure/             # 小节级
│       └── {id}_measure_{k}.tsv
└── paired/                  # 小节级配对集
    └── phrase/              # 乐句级
        └── {id}_phrase_{k}.json
```

---

**报告生成时间**：2026-05-09  
**评估人员**：Claude (Opus 4.7)  
**数据集版本**：PianoCoRe 1.0 + score_processed (2026-05-09)
