# EPR SFT 训练流程计划

> 目标：训练一个面向 **Expressive Piano Rendering (EPR)** 的 LLM，使其能够从乐谱文本 `ABCX` 生成富有演奏表达的 `MIDI-TSV`。  
> 最终任务是 **score-performance rendering**；continuation 和 knowledge QA 是前置适配阶段，用于替代 CPT，让模型掌握音乐文本格式、局部乐感和转换规则。

## 1. 总体目标

EPR 的核心不是“继续写音乐”，而是：

```text
ABCX score
  -> MIDI-TSV performance
```

模型需要学习的能力分为三层：

| 层级 | 能力 | 训练来源 |
|------|------|----------|
| 格式层 | 合法生成 ABCX / MIDI-TSV，小节编号、header、事件字段稳定 | continuation + QA |
| 乐感层 | 理解局部旋律、和声、节奏、力度与踏板文本分布 | continuation |
| 渲染层 | 根据乐谱生成 timing、velocity、duration、pedal 等演奏表达 | rendering |

因此 SFT 不应一次性混合所有材料，而应采用 curriculum：

1. **Stage 1: continuation SFT**  
   让模型熟悉 `ABCX` 和 `MIDI-TSV` 的语言分布，相当于轻量 domain adaptation。

2. **Stage 2: knowledge QA SFT**  
   把格式知识、转换知识、边界规则显式钉住，减少格式漂移。

3. **Stage 3: rendering SFT**  
   用 score-performance paired data 训练最终 EPR 能力。

每个阶段都保存 checkpoint，并在固定 evaluation set 上评估，以便知道模型是在变好还是遗忘。

## 2. PianoCoRe 现有数据解析

本地目录：

```text
PianoCoRe/
├── PianoCoRe-1.0-raw-midi.zip
├── PianoCoRe-1.0-raw-alignments.zip
├── PianoCoRe-1.0-refined.zip
├── composers.csv
└── metadata.csv
```

### 2.1 数据层级

PianoCoRe 按用途分为 C/B/A/A* 四层：

| 层级 | 含义 | 适合用途 |
|------|------|----------|
| PianoCoRe-C | 全量混合来源钢琴 MIDI，未去重、未质量过滤 | 原始分析，不建议直接训练 |
| PianoCoRe-B | 去重并过滤 corrupted / score-like 后的 performance MIDI | performance continuation、大规模乐感适配 |
| PianoCoRe-A | B 中与 score 有 note-level alignment 的 refined score-performance pairs | rendering |
| PianoCoRe-A* | A 中高置信 aligned subset | 高质量 rendering 主训练集 |

本地 `metadata.csv` 统计：

| 集合 | performances | pieces |
|------|--------------|--------|
| all / C | 250,046 | 5,625 |
| B | 214,092 | 5,591 |
| A | 157,207 | 1,591 |
| A* | 130,275 | 1,517 |

来源分布：

| source | performances |
|--------|--------------|
| Aria-MIDI | 200,504 |
| PERiScoPe | 34,773 |
| ATEPP | 11,564 |
| GiantMIDI-Piano | 2,139 |
| ASAP | 1,066 |

质量标签：

| quality_label | count |
|---------------|-------|
| high quality | 228,941 |
| low quality | 19,402 |
| score | 1,244 |
| corrupted | 459 |

### 2.2 文件内容

`raw-midi.zip` 内部结构大致为：

```text
PianoCoRe/raw/<Composer>/<Composition>[/Movement]/
├── score.mxl
├── score_PDMX.mid
├── score_PDMX_mini.mid
├── Aria_*.mid
├── PERiScoPe_*.mid
├── ATEPP_*.mid
└── ...
```

`refined.zip` 内部结构大致为：

```text
PianoCoRe/refined/<Composer>/<Composition>[/Movement]/
├── score_PDMX_refined.mid
├── <performance>_refined.mid
└── <performance>_refined_align.npz
```

`raw-alignments.zip` 包含 raw alignment：

```text
PianoCoRe/raw/<Composer>/<Composition>[/Movement]/
└── <performance>_align.npz
```

`metadata.csv` 是实际构造数据集时的主索引，关键字段包括：

| 字段 | 用途 |
|------|------|
| `composer`, `composition`, `movement` | composition-wise split 与去重 |
| `tier_b`, `tier_a`, `tier_a_star` | 选择 B/A/A* 子集 |
| `score_xml_path`, `score_midi_path` | score continuation / rendering 输入来源 |
| `performance_midi_path` | performance continuation 来源 |
| `refined_score_midi_path` | rendering 的 score MIDI 侧 |
| `refined_performance_midi_path` | rendering 的 performance MIDI 侧 |
| `refined_alignment_path` | note-level alignment |
| `raw_recall`, `raw_precision`, `refined_recall` | alignment 质量过滤 |
| `quality_label` | continuation / rendering 质量过滤 |
| `split` | 官方 train/test split，可作为初始参考 |

### 2.3 数据是否足够

**结论：足够支撑完整 SFT curriculum。**

按任务看：

| 任务 | 可用数据 | 是否足够 | 说明 |
|------|----------|----------|------|
| score continuation | 有 score 的唯一作品，约 1,591-5,591 pieces 视过滤而定 | 足够 | 需要按 score 去重，避免同一 score 被多个 performance 重复放大 |
| performance continuation | CoRe-B 214,092 performances | 很充足 | 是 Stage 1 的主力数据 |
| knowledge QA | 本仓库格式文档 + 自动合成规则问答 | 足够，但需人工审查模板 | 数据量不靠 PianoCoRe，而靠规则覆盖 |
| rendering | CoRe-A 157,207 pairs / A* 130,275 pairs | 很充足 | 最终 EPR 主训练数据，优先 A* 或 `refined_recall >= 0.85` |

本地统计显示，有 score/alignment 的 B 样本为 160,758 条，A/A* 全部有 score 与 refined performance。也就是说：

- **B 全集适合 performance continuation**。
- **B 不能全集用于 score continuation / rendering**，因为并非每条 B 都有可用 score。
- **A/A* 是 rendering 的核心数据**。

### 2.4 当前数据注意事项

1. `PianoCoRe-1.0-raw-midi.zip` 可以正常读取目录。
2. `PianoCoRe-1.0-refined.zip` 和 `PianoCoRe-1.0-raw-alignments.zip` 在本地用 `bsdtar` 可以列出部分内容，但出现 `Truncated input file`；构建 rendering 数据前应校验 zip 完整性，必要时重新下载。
3. PianoCoRe 的 license 是 `CC-BY-NC-SA 4.0`，训练产物用途要匹配非商业和署名继承要求。
4. Aria-MIDI 数量占比很高，训练采样时应按 source 做平衡，避免模型过度拟合某一种转录风格。

## 3. 训练阶段设计

### 3.1 Stage 1: Continuation SFT

目标：让模型熟悉 `ABCX` 与 `MIDI-TSV` 的文本分布、局部音乐结构和小节连续性。

这一阶段用 SFT 取代 CPT。continuation 的答案不需要是唯一正确的音乐答案，重点是让模型学到：

- ABCX header 与 body 的结构；
- 多声部、小节、调号、拍号、时值表达；
- MIDI-TSV header、measure block、note / pedal / marker 行；
- velocity、duration、timing offset 的自然分布；
- 小节间的连续感与局部乐句运动。

#### 数据类型

| 类型 | 输入 | 输出 | 数据源 |
|------|------|------|--------|
| score continuation | `abcx head + M1` | `abcx M2~M5` | 有 score 的唯一作品 |
| performance continuation | `midi-tsv M1` | `midi-tsv M2~M5` | CoRe-B performances |

#### 数据质量

continuation 不需要只用 A* 级别数据，但要守住底线：

- ABCX 必须能 parse；
- MIDI-TSV 必须能 parse；
- 小节编号必须连续；
- note / pedal 事件不能越界；
- 排除 `quality_label=corrupted` 和 `quality_label=score` 的 performance；
- 对 score continuation，按唯一 score 去重，不按 performance pair 重复。

#### 推荐采样

| 子任务 | 占比 |
|--------|------|
| performance continuation | 65-75% |
| score continuation | 25-35% |

performance continuation 是主力，因为 EPR 最终输出是 performance。score continuation 负责补足模型对乐谱语言的理解。

#### Checkpoint

保存为：

```text
epr-sft-s1-continuation
```

### 3.2 Stage 2: Knowledge QA SFT

目标：把格式知识和转换知识显式化，降低 Stage 3 rendering 时的格式漂移。

#### QA 来源

| 来源 | 示例 |
|------|------|
| `wave-roll/MIDI-TSV.md` | MIDI-TSV 行格式、measure 规则、pedal 规则 |
| ABCX 规范与转换脚本 | pitch、duration、voice、header、barline |
| 错误修复模板 | “这段 MIDI-TSV 有什么错误？” |
| 转换规则模板 | “如何把 ABCX M1 的音符映射到 MIDI-TSV？” |
| 边界场景 | `code_start`、pre-measure pedal、空小节、pickup measure |

#### QA 类型

| 类型 | 目标 |
|------|------|
| format QA | 解释字段含义与合法范围 |
| conversion QA | 解释 score-performance rendering 中应保留和生成什么 |
| validation QA | 判断一段 ABCX/MIDI-TSV 是否有效 |
| repair QA | 修复错误格式 |
| policy QA | 明确 `code_start`、M1/M2、header 是否输出等约定 |

#### 混合 replay

Stage 2 建议混入少量 Stage 1 continuation replay：

| 数据 | 占比 |
|------|------|
| QA | 80-90% |
| continuation replay | 10-20% |

#### Checkpoint

保存为：

```text
epr-sft-s2-qa
```

### 3.3 Stage 3: Rendering SFT

目标：训练最终 EPR 能力，即根据 `ABCX score` 输出 `MIDI-TSV performance`。

#### 主要任务格式

有 performance context 的 rendering：

```text
输入：
abcx head + abcx M1~M5
midi-tsv M1

输出：
midi-tsv M2~M5
```

开头 rendering：

```text
输入：
abcx head + abcx M1~M5
performance_context = code_start

输出：
midi-tsv M1~M5
```

这里 `code_start` 表示没有已有演奏上下文，模型需要从乐曲开头生成第一组 performance measures。

#### 数据源

优先级：

1. `tier_a_star=True`
2. `tier_a=True AND refined_recall >= 0.85`
3. `tier_a=True` 的剩余样本，用于扩量或后期低权重混入

推荐先训练干净版本，再扩展：

| 阶段 | 数据 | 目的 |
|------|------|------|
| rendering-clean | A* / `refined_recall >= 0.85` | 学稳定 score-performance 映射 |
| rendering-full | A 中剩余样本低权重混入 | 提升覆盖与鲁棒性 |

#### 混合 replay

Stage 3 不应完全丢掉前两个阶段。建议：

| 数据 | 占比 |
|------|------|
| rendering | 85-92% |
| QA replay | 5-10% |
| continuation replay | 3-5% |

这样可以减少灾难性遗忘，尤其是 MIDI-TSV 长输出格式。

#### Checkpoint

保存为：

```text
epr-sft-s3-rendering
```

如果分 clean/full 两步：

```text
epr-sft-s3a-rendering-clean
epr-sft-s3b-rendering-full
```

## 4. 统一样本格式

所有 SFT 样本建议统一为 instruction/chat 格式，并显式声明任务类型。

### 4.1 Score Continuation

```text
<task>score_continuation</task>
<input_format>abcx</input_format>
<output_format>abcx</output_format>
<instruction>
Continue the ABCX score from the given context. Output only the requested measures.
</instruction>
<context>
ABCX_HEAD
ABCX_M1
</context>
<answer>
ABCX_M2_TO_M5
</answer>
```

### 4.2 Performance Continuation

```text
<task>performance_continuation</task>
<input_format>midi-tsv</input_format>
<output_format>midi-tsv</output_format>
<instruction>
Continue the MIDI-TSV performance from the given measure. Output only M2 to M5.
</instruction>
<context>
MIDI_TSV_HEADER
M1
</context>
<answer>
M2_TO_M5
</answer>
```

### 4.3 Knowledge QA

```text
<task>knowledge_qa</task>
<instruction>
Answer the question about ABCX, MIDI-TSV, or score-performance rendering.
</instruction>
<question>
What does a MIDI-TSV note row represent?
</question>
<answer>
A note row uses <pitch>:<duration> in the first column, onset offset in the second column, and velocity in the third column.
</answer>
```

### 4.4 Rendering

```text
<task>score_performance_rendering</task>
<input_score_format>abcx</input_score_format>
<output_performance_format>midi-tsv</output_performance_format>
<instruction>
Render the given ABCX score into expressive MIDI-TSV. Use the performance context when provided. Output only the requested target measures.
</instruction>
<score_context>
ABCX_HEAD
ABCX_M1_TO_M5
</score_context>
<performance_context>
MIDI_TSV_HEADER
M1
</performance_context>
<answer>
M2_TO_M5
</answer>
```

开头样本：

```text
<performance_context>
code_start
</performance_context>
<answer>
M1_TO_M5
</answer>
```

## 5. 数据切片策略

默认以 5 小节为一个 training window：

| 任务 | context | target |
|------|---------|--------|
| score continuation | M1 | M2-M5 |
| performance continuation | M1 | M2-M5 |
| rendering with context | score M1-M5 + performance M1 | performance M2-M5 |
| rendering from start | score M1-M5 + `code_start` | performance M1-M5 |

后续可以增加多尺度窗口：

| 窗口 | 用途 |
|------|------|
| 2-4 小节 | 训练短局部格式稳定性 |
| 5-8 小节 | 主训练窗口 |
| 9-16 小节 | 长乐句与 phrasing，少量混入 |

多尺度窗口可以提升长上下文能力，但初版应保持 5 小节，先把 pipeline 跑通。

## 6. Evaluation 设计

每个 checkpoint 都必须用同一套 eval 数据评估。

### 6.1 格式指标

| 指标 | 说明 |
|------|------|
| ABCX parse pass rate | 输出是否能被 ABCX parser 接受 |
| MIDI-TSV parse pass rate | 输出是否符合 MIDI-TSV 三列格式 |
| measure continuity | M 编号是否连续，是否输出目标小节 |
| event boundary validity | note/pedal onset 是否在 measure 内 |
| header leakage | target 是否错误输出完整 header 或 prompt 内容 |

### 6.2 音乐结构指标

| 指标 | 说明 |
|------|------|
| pitch consistency | rendering 中输出 pitch 是否与 score 大体一致 |
| onset order | 同小节事件时间是否非负、排序合理 |
| duration range | duration 是否出现极端异常 |
| velocity range | velocity 是否在 0-127 |
| pedal density | pedal 事件密度是否异常 |

### 6.3 Rendering 指标

| 指标 | 说明 |
|------|------|
| pitch F1 | 生成 performance 与 score / target 的 pitch 匹配 |
| onset MAE | 相对 target 的 onset deviation |
| duration MAE | 相对 target 的 duration deviation |
| velocity MAE | 相对 target 的 velocity deviation |
| pedal F1 / MAE | pedal on/off 或连续值误差 |

最终还需要听感评估：

- 随机抽样 rendering；
- 转回 MIDI；
- 用同一音源渲染音频；
- 对比 score-like baseline、真实 performance、模型输出。

## 7. 数据泄漏与切分

必须使用 composition-wise split：

```text
(composer, composition, movement)
```

同一作品的所有 score、performance、segments 必须落在同一 split。原因：

- continuation 可能记住乐谱局部；
- rendering 如果同一作品的不同演奏同时出现在 train/test，会高估效果；
- PianoCoRe 官方论文也采用 composition split。

推荐 split：

| split | 比例 |
|-------|------|
| train | 90% |
| validation | 5% |
| test | 5% |

如果沿用 PianoCoRe 的 `split` 字段，则需要再从 train 中切 validation。

## 8. 训练产物管理

每个阶段保存：

```text
checkpoints/
├── epr-sft-s1-continuation/
├── epr-sft-s2-qa/
├── epr-sft-s3a-rendering-clean/
└── epr-sft-s3b-rendering-full/
```

每个 checkpoint 目录应包含：

```text
checkpoint/
├── model/
├── tokenizer_or_adapter/
├── training_config.yaml
├── dataset_manifest.json
├── eval_results.json
└── sample_outputs/
```

`dataset_manifest.json` 至少记录：

| 字段 | 说明 |
|------|------|
| data source | PianoCoRe version、metadata hash |
| filters | tier、quality_label、refined_recall |
| sample counts | 各任务样本数 |
| split policy | composition split 规则 |
| prompt template version | 样本模板版本 |
| generation date | 数据生成时间 |

## 9. 推荐执行顺序

### Step 0: 数据校验

1. 校验 PianoCoRe zip 完整性。
2. 用 `metadata.csv` 生成数据 manifest。
3. 确定 composition-wise train/val/test split。

### Step 1: 转换格式

1. score MIDI / MusicXML -> ABCX。
2. performance MIDI / refined performance MIDI -> MIDI-TSV。
3. 对 ABCX 和 MIDI-TSV 跑 parser validation。

### Step 2: 构造 Stage 1 continuation 数据

1. 从唯一 score 构造 score continuation。
2. 从 CoRe-B performances 构造 performance continuation。
3. 保存 `sft_stage1_continuation.jsonl`。

### Step 3: 训练并保存 Stage 1

1. 训练 continuation SFT。
2. 保存 `epr-sft-s1-continuation`。
3. 跑固定 eval。

### Step 4: 构造 Stage 2 QA 数据

1. 从格式文档生成 QA。
2. 加入 validation / repair 样本。
3. 混入 10-20% continuation replay。
4. 保存 `sft_stage2_qa.jsonl`。

### Step 5: 训练并保存 Stage 2

1. 从 Stage 1 checkpoint 继续训练。
2. 保存 `epr-sft-s2-qa`。
3. 跑固定 eval，确认 continuation 能力没有明显下降。

### Step 6: 构造 Stage 3 rendering 数据

1. 从 A* 或 `refined_recall >= 0.85` 构造 clean rendering。
2. 构造 `code_start` 和 with-context 两种样本。
3. 混入 QA / continuation replay。
4. 保存 `sft_stage3_rendering_clean.jsonl`。

### Step 7: 训练并保存 Stage 3

1. 从 Stage 2 checkpoint 继续训练。
2. 保存 `epr-sft-s3a-rendering-clean`。
3. 可选：低权重混入 A 全集，继续训练并保存 `epr-sft-s3b-rendering-full`。
4. 跑格式、结构、rendering 和听感评估。

## 10. 主要风险与对策

| 风险 | 对策 |
|------|------|
| 模型学会格式但不会 rendering | Stage 3 提高 rendering 占比，使用 A* 高质量 paired data |
| 模型 rendering 时输出不合法 MIDI-TSV | Stage 2 QA + Stage 3 replay + parser-based eval |
| continuation 记忆作品导致评估虚高 | composition-wise split |
| Aria-MIDI 过度主导 | source-balanced sampling |
| A 中低质量 alignment 污染 | 先用 A* / `refined_recall >= 0.85`，再低权重扩量 |
| refined zip 本地不完整 | 训练前校验并重新下载 |
| 长输出丢小节或重复小节 | 固定 target measure，eval 检查 measure continuity |

## 11. 阶段性判断标准

进入下一阶段前应满足：

| 阶段 | 通过标准 |
|------|----------|
| Stage 1 | ABCX / MIDI-TSV parse pass rate 稳定，continuation 小节连续 |
| Stage 2 | QA 正确率高，格式修复能力提升，continuation 无明显遗忘 |
| Stage 3a | rendering 输出合法，pitch 与 score 高一致，velocity/timing 有表达变化 |
| Stage 3b | 扩量后 rendering 指标不下降，听感不变差 |

最终成功标准：

1. 输出 MIDI-TSV 可稳定转回 MIDI。
2. 相比 score-like baseline，模型输出有自然 timing、velocity、duration 和 pedal 变化。
3. 与真实 performance 的统计特征接近。
4. 主观听感不机械，不出现明显坏音、错位、极端踏板。

