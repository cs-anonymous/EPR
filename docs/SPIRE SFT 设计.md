# SPIRE / EPR SFT 设计（合并稿）

> 本文档合并了原 `SPIRE SFT 设计.md` 与 `EPR_SFT_PLAN.md`。  
> 目标是定义一条以 **Expressive Piano Rendering (EPR)** 为核心的 SFT 路线：从乐谱侧输入生成 expressive performance，而不是把 continuation 当作主任务。

## 1. 核心判断：CPT 还是 SFT

- 如果目标是论文任务效果，尤其是 `score -> performance`、`format conversion`、`repair`，则 **SFT 优先**。
- 如果目标是训练一个通用音乐文本基础模型，要求大规模无监督补全、开放式续写、风格迁移，则 CPT 更重要。
- 当前项目的主目标是 EPR，因此主路线应是：

```text
Base LLM
  -> Language Learning SFT（仅保留 mask / QA / repair）
  -> EPR Branch SFT
  -> spire-sft-epr
```

这里的 Language Learning 不再承担“继续写音乐”的 continuation 目标，而是承担：

- 让模型熟悉 `ABCX`、`Score MIDI-TSV`、`Performance MIDI-TSV` 三种结构化文本；
- 显式学习各字段与 mask 的恢复规则；
- 降低后续 EPR 阶段的格式漂移。

## 2. 符号体系

### 2.1 语言与样本

| 符号 | 含义 |
|---|---|
| $\Sigma$ | ABCX 乐谱语言 / 乐谱集 |
| $\Psi$ | Score MIDI-TSV 语言 / 乐谱 MIDI 集 |
| $\Phi$ | Performance MIDI-TSV 语言 / 演奏集 |
| $\sigma \in \Sigma$ | 一首具体 ABCX 乐谱 |
| $\psi \in \Psi$ | 一首具体 score MIDI-TSV |
| $\phi \in \Phi$ | 一次具体 expressive performance |

### 2.2 结构粒度

| 符号 | 含义 |
|---|---|
| $\sigma_{M_k}, \psi_{M_k}, \phi_{M_k}$ | 第 $k$ 个逻辑小节 |
| $\sigma_{H_k}, \psi_{H_k}, \phi_{H_k}$ | 第 $k$ 个启发式乐句 |
| $\sigma_{\text{head}}$ | ABCX 头部（调号、拍号、速度、metadata 等） |
| $\sigma_{M_{i..j}}$ | 从第 $i$ 到第 $j$ 个连续小节的 ABCX span |
| $\psi_{M_{i..j}}$ | 从第 $i$ 到第 $j$ 个连续小节的 score MIDI span |
| $\phi_{M_{i..j}}$ | 从第 $i$ 到第 $j$ 个连续小节的 performance span |

### 2.3 Mask 函数

| 记号 | 含义 |
|---|---|
| $f(\sigma)$ | 对 ABCX 乐谱做 mask |
| $u(\psi)$ | 对 score MIDI-TSV 做 mask |
| $g(\phi)$ | 对 performance MIDI-TSV 做 mask |

推荐的 mask 变体：

| 语言 | 变体 | 说明 |
|---|---|---|
| $\Sigma$ | `acc`, `treble`, `bass`, `label` | 恢复升降号、声部、文本标记 |
| $\Psi$ | `timing`, `duration`, `structure` | 恢复 score MIDI 的时值与结构字段 |
| $\Phi$ | `timing`, `velocity`, `duration`, `pedal` | 恢复 expressive 属性 |

> 这里用 $\Psi$ / $\psi$ 表示 score MIDI，避免继续使用 `phi0` 这种容易和 performance 混淆的命名。

## 3. PianoCoRe 数据与任务边界

当前 EPR 主实验依赖以下对象：

- `score_abcx_path`：ABCX 乐谱
- `score_midi_path` / `refined_score_midi_path`：score MIDI
- `refined_performance_midi_path`：performance MIDI
- `refined_alignment_path`：`align.npz`

配对训练的主力子集仍然是：

| 集合 | 含义 | 用途 |
|---|---|---|
| CoRe-A | 有 refined note-level 对齐的 score-performance pairs | 可用于扩量 |
| CoRe-A* | 高置信 refined aligned subset | EPR 主训练集 |

未配对或弱配对数据仍然有价值，但主要用于 Language Learning 的 mask / QA / repair，不再用于 continuation。

## 4. 数据挖掘与对齐流程

假设所有 score `mxl/xml` 已经生成了对应的原始 `ABCX`。

### 4.1 Step 1：从 Score MIDI 定义逻辑小节

输入：

- score MIDI

输出：

- 一个 piece-level JSON，定义这首曲子的“逻辑小节”

核心目标：

- 用 score MIDI 作为小节边界主轴；
- 得到稳定的 `M1, M2, ...` 逻辑小节编号；
- 记录每个逻辑小节的起止 tick、时长、拍号相关信息；
- 为后续 ABCX 与 performance 侧提供统一对齐坐标系。

建议 JSON 字段：

```json
{
  "piece_id": "...",
  "measures": [
    {
      "measure_id": "M1",
      "start_tick": 0,
      "end_tick": 1920,
      "duration_tick": 1920
    }
  ]
}
```

### 4.2 Step 2：识别 ABCX 乐句并与逻辑小节对齐

输入：

- 原始 ABCX
- Step 1 输出的逻辑小节 JSON

处理目标：

1. 用启发式算法识别原始 ABCX 的乐句；
2. 去掉原始 ABCX body 中已有的小节号噪声，仅保留每个小节的纯内容；
3. 让每个 ABCX 小节内容对齐到一个 score MIDI 逻辑小节；
4. 如果存在多余音符或多余小节，则截断到逻辑小节坐标系；
5. 生成可还原的乐句结构表示。

目标 ABCX 结构形如：

```text
H1\t|:M1|M2|$M3|M4:|$
M1\t!p!"^Allegro ma con tenerezza" ([ce]4 ; z4 ; "^con pedale" z A,A,A,
M2\t!<(! [df]4 ; z4 ; z A,A,A,
M3\t[B^g]4!<)! ; z4 ; z A,A,A,
M4\t[ca]4) ; z4 ; !f! z (A,E,C,
H2\tM5|M6|$M7|...
M5\t(c'e){/g}(fe) ; z4 ; A,,4)
M6\t(e2 ^d) z ; z4 ; z (B,,B,A,
M7\t(b=d){/f}(ed) ; z4 ; ^G,4)
```

其中：

- `Hk` 行保存乐句结构；
- `Mk` 行保存该小节的实际 ABCX 内容；
- `M` 表示引用对应小节内容；
- `$` 表示换行；
- `Hk + 所有 Mk` 必须能够**无损还原**规范化后的 aligned ABCX。

建议把以下信息写回 JSON：

```json
{
  "phrases": [
    {
      "phrase_id": "H1",
      "structure": "|:M1|M2|$M3|M4:|$",
      "measures": ["M1", "M2", "M3", "M4"]
    }
  ],
  "measure_to_phrase": {
    "M1": "H1",
    "M2": "H1"
  }
}
```

### 4.3 Step 3：根据 JSON 与 `align.npz` 对齐 performance

输入：

- performance MIDI / performance MIDI-TSV
- Step 2 输出的 JSON
- `align.npz`

处理目标：

1. 根据 score 逻辑小节把 performance 分配到相同的 `M1, M2, ...`；
2. 自动检测 repeat，并复用相同的小节定义；
3. 继承 `measure_to_phrase`，把 performance 的每个 measure 分配到对应乐句；
4. 如果当前小节所在乐句与前一小节不同，或者当前小节是该乐句第一个小节，则插入乐句符号。

输出目标：

- `\psi_{M_k}`：score MIDI 的 measure serialization
- `\phi_{M_k}`：performance MIDI 的 measure serialization
- `\psi_{H_k}` / `\phi_{H_k}`：按 `measure_to_phrase` 聚合后的 phrase serialization

### 4.4 统一约束

- 所有三侧（ABCX / score MIDI / performance MIDI）共用同一套逻辑小节编号；
- phrase 结构以 score 为主轴，performance 继承分配；
- 跨 phrase 的 span 完全允许，不要求 phrase 间严格独立；
- 数据构建优先保证“可复现、可还原、可验证”，其次再做启发式美化。

## 5. 任务体系

本文只保留三类任务：

1. Language Learning
2. EPR 主实验
3. EPR baseline / ablation

CSR 可继续作为后续分支，但不作为当前文档主线。

### 5.1 Language Learning：仅保留 mask / QA / repair

Language Learning 不再包含 continuation。

保留任务：

| 子任务 | 公式 | 说明 |
|---|---|---|
| Score mask | $\sigma_{\text{head}} + f(\sigma_{M_k}) \rightarrow \sigma_{M_k}$ | 学 ABCX 结构恢复 |
| Score-MIDI mask | $u(\psi_{M_k}) \rightarrow \psi_{M_k}$ | 学 score MIDI-TSV 字段恢复 |
| Performance mask | $g(\phi_{M_k}) \rightarrow \phi_{M_k}$ | 学 expressive 属性恢复 |
| QA / validation / repair | 规则问答、合法性判断、格式修复 | 钉住边界规则 |

建议保留 measure-level mask 为主，phrase-level mask 作为可选增强，而不是主配方。

推荐比例：

| 任务 | 比例 |
|---|---|
| Score mask + Score-MIDI mask | 40-50% |
| Performance mask | 35-45% |
| QA / validation / repair | 10-20% |

保存 checkpoint：

```text
spire-sft-language-mask
```

### 5.2 EPR 主实验：Span-ABCX2PM

这是当前最重要的主实验。

#### 主任务定义

```text
ABCX2PM-main:
σ_head + σ_M_prev + σ_M_{i..j} + φ_M_prev -> φ_M_{i..j}
```

其中：

- `i, j` 动态决定；
- 从 `j=i` 开始不断扩展；
- 只要完整样本不超过 `max_length=1536`，就继续添加长度；
- 不需要额外看下一个小节；
- 允许跨 phrase；
- 只有 `coldstart` 和 `main`，没有 `ending`。

冷启动版本：

```text
ABCX2PM-coldstart:
σ_head + σ_M_{1..j} -> φ_M_{1..j}
```

#### 设计理由

- 比固定 3-measure window 更接近真实 rendering；
- 比 phrase-based EPR 更少依赖启发式 phrase 边界质量；
- token 利用率更高，重复上下文更少；
- 允许模型直接学习跨乐句的连续表达结构。

### 5.3 EPR 主实验：Span-SM2PM

这是第二个主实验，与 `ABCX2PM` 互补。

#### 主任务定义

```text
SM2PM-main:
ψ_M_prev + ψ_M_{i..j} + φ_M_prev -> φ_M_{i..j}
```

冷启动版本：

```text
SM2PM-coldstart:
ψ_M_{1..j} -> φ_M_{1..j}
```

与 `ABCX2PM` 相同：

- 只有 `coldstart` 和 `main`；
- 不设 `ending`；
- `j` 按 `max_length=1536` 动态扩展；
- 允许跨 phrase。

#### 设计理由

- 把“乐谱抽象结构理解”和“演奏表达生成”之间加入一个更接近 performance 语言的中间表征；
- 可以直接研究 `score MIDI -> expressive performance` 的映射；
- 在一些场景下比纯 ABCX 输入更利于 timing / duration 对齐。

### 5.4 EPR baseline / ablation

以下任务不再是主实验，而是对照实验：

| 任务 | 公式 | 角色 |
|---|---|---|
| Measure EPR | $\sigma_{\text{head}} + \sigma_{M_{k-1}} + \sigma_{M_k} + \sigma_{M_{k+1}} + \phi_{M_{k-1}} \rightarrow \phi_{M_k}$ | baseline |
| Phrase EPR | $\sigma_{\text{head}} + M_{\text{prev}} + \sigma_{H_k} + M_{\text{next}} + \phi_{M_{\text{prev}}} \rightarrow \phi_{H_k}$ | baseline |

这些旧任务的价值主要是：

- 提供和已有 pipeline 的直接可比性；
- 验证 span 方案是否真的优于固定边界方案；
- 在主实验 early failure 时提供稳定 fallback。

## 6. Span 样本构造策略

### 6.1 基本规则

对 `ABCX2PM` 与 `SM2PM`，都采用同一套 span 采样：

1. 固定起点 `i`
2. 从 `j=i` 开始
3. 不断尝试加入 `M_{j+1}`
4. 若完整样本 token 长度仍不超过 `1536`，则接受并继续扩展
5. 一旦超过 `1536`，回退到上一个合法 `j`
6. 为该起点 `i` 只保留一个“最长合法 span”

完整长度应按真实训练文本估算，而不是只按 target 长度估算。

### 6.2 `task_type`

只保留：

| 类型 | 定义 |
|---|---|
| `coldstart` | 没有 previous performance context 的开头 span |
| `main` | 有 `M_prev` 与 `φ_M_prev` 的普通 span |

不再单独定义 `ending`。

### 6.3 窗口重合策略

默认建议：

- **主实验默认不做 target overlap**
- 对于一个 span `[i, j]`，下一个 span 从 `j + 1` 开始
- 也就是说，下一个样本只通过 `M_prev = M_j` 与 `φ_M_prev = φ_M_j` 继承上下文

理由：

- 已经有 `M_prev` / `φ_M_prev` 作为连续性桥梁；
- span 本身较长，再做大量 overlap 会明显增加冗余；
- 作为主实验，更应优先观察“长 span 本身”的效果，而不是把数据量堆在重复区域上。

可选增强：

- 作为额外 ablation，可加入少量重叠样本，例如 10-20%；
- 如果确实要做 overlap，优先考虑“轻重叠”，而不是强制 phrase-aware 回退很多小节；
- 不建议把“下一个样本永远从上一个 `M_j` 所在乐句的前一小节开始”作为默认规则，因为这会引入较重冗余，并把采样偏置绑到启发式 phrase 边界上。

## 7. 统一样本格式

建议统一为 instruction/chat 格式，但在字段层面明确保留不同输入视图。

### 7.1 ABCX2PM

```json
{
  "task": "epr_span",
  "variant": "abcx2pm",
  "task_type": "main",
  "instruction": "Render the target score span into expressive performance.",
  "score_header": "σ_head",
  "score_snip": "σ_M_prev + σ_M_{i..j}",
  "perf_context": "φ_M_prev",
  "perf_target": "φ_M_{i..j}"
}
```

### 7.2 SM2PM

```json
{
  "task": "epr_span",
  "variant": "sm2pm",
  "task_type": "main",
  "instruction": "Render the target score-MIDI span into expressive performance.",
  "score_midi_snip": "ψ_M_prev + ψ_M_{i..j}",
  "perf_context": "φ_M_prev",
  "perf_target": "φ_M_{i..j}"
}
```

说明：

- `SM2PM` 不建议把 `ψ` 伪装成 `score_snip`；
- 既然它是主实验，就应在 schema 上明确区分 ABCX 视图与 score-MIDI 视图。

## 8. 推荐训练流程

### 8.1 Step 1：Language Learning

训练内容：

- Score mask
- Score-MIDI mask
- Performance mask
- QA / validation / repair

不包含：

- score continuation
- performance continuation
- EPR rendering

保存：

```text
spire-sft-language-mask
```

### 8.2 Step 2：EPR Branch

从 `spire-sft-language-mask` 初始化，训练：

- `ABCX2PM-main`
- `ABCX2PM-coldstart`
- `SM2PM-main`
- `SM2PM-coldstart`

建议把这两类主实验作为主要训练流，而不是把旧的 measure / phrase EPR 放在中心。

推荐比例：

| 任务 | 比例 |
|---|---|
| `ABCX2PM` | 45-55% |
| `SM2PM` | 35-45% |
| baseline / replay | 0-15% |

若模型出现明显格式遗忘，可少量加入：

- mask replay
- QA / repair replay

优先 replay 这些结构性任务，而不是回到 continuation。

保存：

```text
spire-sft-epr-span
```

### 8.3 Step 3：Baseline / Ablation

额外训练或对照：

- `measure_epr`
- `phrase_epr`

它们的职责是做比较，不再作为主线。

## 9. 评估设计

### 9.1 基础合法性

| 指标 | 说明 |
|---|---|
| parse success rate | 输出是否能被对应 parser 接受 |
| measure continuity | span 内小节是否连续、无遗漏、无重复 |
| event validity | note / pedal / timing 是否越界 |
| output boundary correctness | 是否只输出目标 span，不泄漏 prompt 结构 |

### 9.2 Rendering 指标

| 指标 | 说明 |
|---|---|
| pitch consistency | 与 score / target 的音高匹配程度 |
| onset MAE | onset 偏差 |
| duration MAE | duration 偏差 |
| velocity MAE | velocity 偏差 |
| pedal F1 / MAE | 踏板误差 |

### 9.3 Span 特有分析

建议增加：

| 字段 / 指标 | 用途 |
|---|---|
| `span_measure_count` | 观察模型对不同 span 长度的稳定性 |
| `crosses_phrase_boundary` | 比较跨 phrase 与不跨 phrase 的效果 |
| `variant` | 分析 `abcx2pm` 与 `sm2pm` 的差异 |

## 10. 当前结论

1. 当前 EPR 主实验应从“固定 measure / phrase window”转向“动态 measure span”。
2. `ABCX2PM` 与 `SM2PM` 是主实验；旧 `measure_epr` / `phrase_epr` 是 baseline。
3. Language Learning 只保留 mask / QA / repair，不再保留 continuation。
4. `score MIDI` 应使用新符号 $\Psi$ / $\psi$，不要继续使用 `phi0`。
5. span 构造默认不做 target overlap；若要做 overlap，应作为额外 ablation，而不是主配方。
