# Piano Performance Model 研究

> 从"音乐怎么生成"转向"乐谱怎么演奏"。
>
> 核心问题：**给定 Score/纯MIDI → 输出富含演奏意图的 MIDI**（timing deviation, dynamics, articulation, pedaling），可通过顶级音源（Yamaha, Logic Pro, Pianoteq）合成具有真实感的演奏。
>
> 本文档从 [[Music Generation研究]] 中抽离，聚焦 Score→Performance 这一特定子问题。

## 一、问题定义：从"弹什么"到"怎么弹"的范式转变

### 核心映射：Score MIDI → Performance MIDI

```
Score MIDI (quantized, mechanical)
  ├─ pitch (精确)
  ├─ onset_time (网格对齐)
  ├─ duration (理论值)
  └─ velocity (固定或无意义)

         ↓  Performance Model

Performance MIDI (expressive, human-like)
  ├─ pitch (不变)
  ├─ onset_time + Δonset (rubato, ±几十ms)
  ├─ duration + Δduration (articulation: legato/staccato)
  ├─ velocity curve (crescendo, diminuendo, phrase shaping)
  ├─ pedal events (sustain, una corda, sostenuto)
  └─ micro-timing (swing, groove, individual finger timing)
```

**Performance = Score + Deviation。演奏即是对乐谱的系统性偏离。**

### 与 Music Generation 的根本区别

| 维度   | Music Generation | Piano Performance Model       |
| ---- | ---------------- | ----------------------------- |
| 输入   | 无 / 文本 prompt    | Score MIDI（确定性的音符序列）          |
| 输出   | 音符 + 演奏          | 仅演奏偏差（Δonset, Δvelocity, ...） |
| 创造性  | 高（作曲+演奏）         | 中低（仅演奏诠释）                     |
| 评价标准 | 主观（好听吗？结构完整吗？）   | 相对客观（接近真实演奏吗？）                |
| 数据需求 | 极大量              | 可控（仅需 score-performance 配对）   |
| 应用   | 创意工具             | 演奏辅助、自动伴奏、教育                  |

**关键优势：输入 Score 已经确定了"弹什么"，模型只需学习"怎么弹"，问题空间大幅缩小。**

---

## 二、演奏表达的维度分解：五层结构与各自的可建模性

### Timing（时间层）——节奏的呼吸

| 子维度 | 描述 | 典型范围 | 感知重要性 |
|--------|------|---------|-----------|
| **Tempo curve** | 整体速度波动（rit./accel.） | ±10-20% BPM | ★★★★★ |
| **Rubato** | 局部时间伸缩（旋律延迟/提前） | ±20-80ms | ★★★★★ |
| **Melody lead** | 旋律音相对伴奏音提前 | 10-50ms | ★★★★ |
| **Chord asynchrony** | 和弦内音符非同时（arp/rolled chord） | 5-30ms | ★★★ |
| **Beat subdivision** | 拍内微偏移（swing/groove） | ±10ms | ★★★ |

### Dynamics（力度层）——强弱的轮廓

| 子维度 | 描述 | 典型范围 | 感知重要性 |
|--------|------|---------|-----------|
| **Velocity curve** | 连续力度轮廓（非离散值） | 30-120 (continuous) | ★★★★★ |
| **Crescendo/Diminuendo** | 渐强/渐弱的 slope | 跨 2-8 小节 | ★★★★★ |
| **Melody voicing** | 旋律音突出（相对伴奏高 10-20%） | 每和弦内 | ★★★★ |
| **Accent pattern** | 重音模式（与节拍结构相关） | 局部 | ★★★★ |
| **Dynamic contrast** | 段落间力度差异（pp vs ff） | 全局 | ★★★★★ |

### Articulation（触键层）——音符的连接方式

| 子维度 | 描述 | MIDI 表现 | 感知重要性 |
|--------|------|-----------|-----------|
| **Legato/Staccato** | 音符连接度 | duration ratio (0.3~1.2×理论值) | ★★★★★ |
| **Note overlap** | 相邻音符重叠量 | overlap ms | ★★★★ |
| **Release velocity** | 释键速度（部分MIDI支持） | release event | ★★ |
| **Aftertouch** | 触后压力 | channel pressure | ★★★ |

### Pedaling（踏板层）——和声的延续与色彩

| 子维度 | 描述 | MIDI CC | 感知重要性 |
|--------|------|---------|-----------|
| **Sustain pedal** | 延音踏板开/关 | CC64 (0-127) | ★★★★★ |
| **Half-pedaling** | 半踏板（连续控制） | CC64 (中间值) | ★★★★ |
| **Sostenuto** | 选择性延音 | CC66 | ★★ |
| **Una corda** | 弱音踏板 | CC67 | ★★★ |
| **Pedal timing** | 踏板切换与音符的精确配合 | onset 关联 | ★★★★ |

> **演奏者视角修正**：学术论文常将 pedaling 列为"最薄弱环节"，这是**方法论错误的产物**——他们试图从 MIDI 数据中"猜"踏板模式，而演奏者的踏板逻辑是高度规则化的：和声变化 → 换踏板（最常见规则）；旋律连音线 → 保持踏板；谱面标记 Ped./✻ → 严格执行。**Pedaling 反而是最容易用规则+知识注入解决的维度**，因为规则清楚、谱面可查、和声可分析。真正困难的是 rubato 和 phrasing——谱上没有明确标记，靠演奏者的直觉和风格传统。

### Phrasing（乐句层）——跨 Note 的全局表达

这不是单个 note 的属性，而是 **sequence-level 模式**：
- **Phrase boundary**：乐句末尾的 rallentando + diminuendo + breath pause
- **Phrase arc**：乐句内部的力度拱形（crescendo → peak → diminuendo）
- **Tension/Release**：跨乐句/段落的张力累积与释放

**Phrasing 是 Performance Model 最核心的挑战——它不能通过 note-by-note 的独立建模得到，必须 sequence-level 建模。**

---

## 三、研究现状评估：一个小众但真实存在的方向

### 研究规模：远小于 Music Generation 的冷门领域

这个领域的研究者群体远小于 Music Generation，主要由以下构成：

| 阵营                 | 代表机构/团队                                           | 活跃程度                       |
| ------------------ | ------------------------------------------------- | -------------------------- |
| **学术 MIR 社区**      | ISMIR 社区（奥地利 JKU Linz 的 Widmer 组、西班牙 UPC、英国 QMUL） | 持续但小众                      |
| **Google Magenta** | Google Brain 团队                                   | 2018-2020 有活跃产出，之后重心转向音频生成 |
| **Yamaha 研究部门**    | Yamaha Corporation（日本）                            | 内部研究为主，部分公开发表              |
| **独立研究者**          | 分散在各高校的音乐信息处理组                                    | 零星产出                       |

**与 Music Generation 对比：**

|             | Music Generation                    | Expressive Performance |
| ----------- | ----------------------------------- | ---------------------- |
| ISMIR 年度论文数 | ~20-40 篇                            | ~3-8 篇                 |
| 大厂投入        | Google(DeepMind), Meta, Adobe, Suno | 几乎没有                   |
| 开源项目        | 数十个                                 | 个位数                    |
| 商业化程度       | Suno/Udio 等已商业化                     | 尚未商业化                  |

**核心结论：这个领域没有被"大部队"占领，但也意味着——如果能做出显著超越现有水平的成果，这个方向存在蓝海机会。**

### 为什么这个方向没有被大规模攻克？

1. **数据天花板明显**：MAESTRO 仅 200h，而 Music Generation 可以无限制使用互联网 MIDI
2. **评估困难**：不像图像生成有 FID，演奏质量评估高度依赖主观判断
3. **商业动机不足**：Suno 可以直接卖生成结果，但 Performance Model 只是中间工具
4. **学术偏见**：MIR 社区更关注"识别"和"生成"，"渲染/演奏"被视为边缘问题
5. **问题本身比表面复杂**：一对多问题（同一乐谱有无数种演奏）让确定性建模变得困难

### 方法演进：从规则到深度学习

| 时期              | 方法                            | 核心思想                          | 代表工作             |
| --------------- | ----------------------------- | ----------------------------- | ---------------- |
| **2000s-2010s** | Rule-based (KTH)              | 手工规则：旋律音提前、结尾减速等              | Widmer, Goebl    |
| **2010s**       | HMM / CRF                     | 将演奏视为序列标注问题                   | Grachten et al.  |
| **2010s**       | Regression                    | 对每个 note 预测 Δonset, Δvelocity | 多种线性/非线性回归       |
| **2018**        | Performance RNN               | 引入 expressive control token   | Google Magenta   |
| **2019**        | Piano Tree / Seq2Seq          | 专为钢琴设计的层次化建模                  | Hawthorne et al. |
| **2019+**       | Transformer / VAE / Diffusion | 自注意力 + 多模态分布                  | 多篇 ISMIR 论文      |

**传统方法的局限：规则是固定的、风格单一的、缺乏上下文感知。**

---

## 四、现有方法的效果瓶颈：为什么还是"一听就是机器"

### 效果分层：当前 SOTA 处于什么水平

```
┌─────────────────────────────────────────────────┐
│  Level 5: 专业钢琴家的真实演奏（人类无法分辨）    │  ← 目标
├─────────────────────────────────────────────────┤
│  Level 4: 接近真实，专业人士能察觉细微差异       │  ← 尚未达到
├─────────────────────────────────────────────────┤
│  Level 3: "还不错"但明显是机器演奏               │  ← 当前 SOTA 附近
├─────────────────────────────────────────────────┤
│  Level 2: 有表达但不自然（节奏不均匀、力度生硬）   │  ← 早期深度学习方法
├─────────────────────────────────────────────────┤
│  Level 1: 有动态变化但不一致                     │  ← Performance RNN 级别
├─────────────────────────────────────────────────┤
│  Level 0: 量化 MIDI，无演奏表达                  │  ← 基线
└─────────────────────────────────────────────────┘
```

### 各维度的实际建模难度：谱面信息决定一切

| 维度                    | 当前学术水平     | 谱面信息量 | 规则明确度 | 实际建模难度 | 说明                               |
| --------------------- | ---------- | ----- | ----- | ------ | -------------------------------- |
| **Pedaling**          | Level 1-2* | ★★★★★ | ★★★★★ | 最易     | *学术低分是因为方法错——有谱面和和声分析即可高精度建模     |
| **Articulation**      | Level 2-3  | ★★★★  | ★★★★  | ⭐⭐     | 连/断有谱面标记（连音线、跳音点），规律性强           |
| **Velocity/Dynamics** | Level 3    | ★★★★  | ★★★   | ⭐⭐⭐    | pp-ff 有标记，crescendo 有符号，但曲线细节需学习 |
| **Tempo curve**       | Level 3-4  | ★★★   | ★★★   | ⭐⭐⭐    | rit./accel. 有文字标记，但 rubato 幅度需学习 |
| **Rubato/Timing**     | Level 2-3  | ★★    | ★★    | ⭐⭐⭐⭐   | 谱面几乎没有精确标记，高度依赖演奏者个人风格           |
| **Phrasing**          | Level 2    | ★     | ★     | ⭐⭐⭐⭐⭐  | 乐句弧线高度直觉化，最难建模                   |
| **Style consistency** | Level 2    | —     | ★★★   | ⭐⭐⭐⭐   | 需要建模演奏家个人风格偏好                    |

**核心推论：难度 = 1 / (谱面信息密度 + 规则明确度)。谱上写得越清楚、规则越明确的东西，越容易用规则或知识注入解决；谱上模糊的、依赖演奏者个人理解和风格的东西，才是真正需要深度学习建模的。**

### 人类盲听测试结果：最好的模型仍有明显破绽

| 研究 | 方法 | 人类分辨准确率 | 说明 |
|------|------|--------------|------|
| Widmer (2000s) | KTH Rules | ~70-80% 能分辨 | 规则方法明显可分辨 |
| Performance RNN (2018) | RNN | ~60-70% 能分辨 | 有改进但仍可分辨 |
| Piano Transformer (2019) | Transformer | ~55-65% 能分辨 | 接近随机但有统计显著性 |
| 人类真实演奏 | — | ~50% (随机) | 作为对照组 |

**最好的学术模型已经能做到 60-70% 的人类无法分辨，但离"完全骗过专业人士"还有明显差距。差距主要体现在 pedaling 不自然、phrasing 缺少弧线、timing 微变不够细腻。**

### 学术效果不够好的深层原因：方法论的根本偏差

| 问题 | 学术做法 | 演奏者视角的正确做法 |
|------|---------|---------------------|
| **Pedaling** | 从 MIDI 数据中学习踏板模式 | 直接从 Score 的和声分析 + 谱面标记推导 |
| **Timing** | 纯回归预测 Δonset | 区分规则性部分（rit.标记）和学习性部分（rubato风格） |
| **Dynamics** | 回归 velocity 值 | 结合谱面标记（pp-ff）作为引导，学习曲线细节 |
| **整体** | 纯数据驱动，把演奏当信号处理 | **规则 + 学习混合**：规则解决确定性问题，学习解决风格性问题 |

### 效果瓶颈的四个根源

1. **数据量不足**：200h MAESTRO 对深度学习来说太小。对比音频生成的 30 万小时
2. **一对多问题未解决**：大多数模型预测"平均演奏"，而真实演奏是多样化的
3. **评估指标偏差**：优化 timing RMSE ≠ 演奏好听（人类感知的非线性）
4. **缺少高层音乐知识注入**：纯数据驱动方法不懂"这里应该是高潮""这里是过渡"

---

## 五、数据基础：可用的数据集及其局限

### 核心数据集对比

| 数据集                            | 内容                                   | 规模             | Score-Performance 配对             | 适用性   |
| ------------------------------ | ------------------------------------ | -------------- | -------------------------------- | ----- |
| **MAESTRO v3.0**               | 钢琴 MIDI + audio                      | 200h / 1,278 首 | ✅ 天然配对（audio→MIDI via alignment） | ★★★★★ |
| **Yamaha e-Piano Competition** | 专业钢琴家 MIDI                           | ~70 首          | ✅ 有对应乐谱                          | ★★★★  |
| **ASAP Dataset**               | 对齐的 Score + Audio + Performance MIDI | 194 首          | ✅ 精确对齐                           | ★★★★★ |
| **Piano-e-Competition**        | 多钢琴家演奏同一曲目                           | 有限             | ✅                                | ★★★★  |
| **POP909**                     | 流行钢琴 MIDI                            | ~900 首         | ❌ 无 score 对齐                     | ★★    |
| **Lakh MIDI**                  | 大规模 MIDI 集合                          | 170k+          | ❌ 混杂                             | ★     |

### MAESTRO 详解：当前最佳数据源

**MAESTRO (MIDI and Audio Edited for Synchronous TRacks and Organization)**：

- **来源**：国际钢琴电子竞赛（Piano-e-Competition）
- **内容**：Disklavier 钢琴演奏的 MIDI + 录音
- **对齐精度**：亚毫秒级（通过 forced alignment）
- **MIDI 质量**：包含 velocity, timing, pedal — 接近真实演奏
- **格式**：每个文件包含 performance MIDI 和对应的 "quantized" MIDI（可用作 score）

每个 note 包含的关键信息：
```
note_on_time (seconds, high precision)
note_off_time (seconds)
pitch (MIDI 0-127)
velocity (0-127)
pedal events (CC64)
instrument (always Disklavier grand piano)
```

### ASAP 数据集：拥有明确的 Score 层

**ASAP (Aligned Scores and Audio Performances)**：
- 包含 MusicXML score + 对齐的 performance MIDI + audio
- 对齐方法：基于动态时间规整（DTW）
- 曲目：以古典钢琴为主
- **优势**：有明确的 score 层（MusicXML），可以直接提取纯净乐谱

### 数据量评估：与主流深度学习的差距

```
MAESTRO:    200h 钢琴 ≈ ~1,000,000 notes (rough estimate)
ASAP:       194 首 ≈ ~200,000 notes

对比 LLM 训练: 这远不够做 pretraining
但作为 fine-tuning / specialized model: 可能足够
```

**数据量是 Performance Model 的硬约束，这也决定了必须采用"知识注入 + 小数据高效学习"的策略，而非纯数据驱动的暴力训练。**

---

## 六、技术方案设计：从表示、架构到训练策略的完整方案

### 表示方案：Score → Performance 的 Tokenization

核心设计原则：
1. **Score 是确定的**（不需要 tokenization 的不确定性）
2. **Performance 偏差是连续的**（timing ms, velocity value）
3. **需要保持 sequence-native**（时间推进）

#### 方案 A：连续参数回归

```
Input:  Score note sequence
        [(pitch₁, onset₁, duration₁), (pitch₂, onset₂, duration₂), ...]

Model:  Transformer / RNN

Output: Per-note continuous parameters
        [(Δonset₁, Δduration₁, velocity₁, legato₁),
         (Δonset₂, Δduration₂, velocity₂, legato₂), ...]
        + Per-phrase parameters (tempo curve, dynamics curve)
        + Pedal events (CC64 sequence)
```

**优点**：直接输出连续值，无量化误差。**缺点**：回归模型的 multimodal 问题（同一 score 有无数种演奏）。

#### 方案 B：离散化 + 分类

```
Δonset:    量化为 20 bins (-100ms ~ +100ms, 10ms/bin)
Δduration: 量化为 ratio bins (0.5× ~ 1.5×)
velocity:  量化为 32 bins (或直接使用 0-127)
pedal:     CC64 离散值
```

**优点**：分类问题更稳定，容易做多模态（predict distribution）。**缺点**：量化损失精度。

#### 方案 C：混合方案（推荐）

```
Timing (Δonset):     连续回归（ms 级别精度）
Duration ratio:      连续回归（0.3 ~ 1.5）
Velocity:            连续回归 + 后处理到 MIDI 整数
Pedal:               二分类 (on/off) + 连续 intensity
```

### 模型架构：Score-conditioned Transformer

```
┌─────────────────────────────────────────┐
│  Score Encoder                           │
│  Input: (pitch, onset, duration, context) │
│  Output: hidden states per note          │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  Performance Decoder                     │
│  Input: score hidden + prev performance  │
│  Output: (Δonset, Δdur, vel, pedal)     │
└─────────────────────────────────────────┘
```

| 决策 | 选项 | 推荐 | 理由 |
|------|------|------|------|
| **编码方式** | Autoregressive / Non-AR | Autoregressive | 演奏有时间因果性 |
| **多模态** | Single output / Mixture | Mixture (e.g. GMM) | 同一 score 有不同演奏风格 |
| **上下文窗口** | Local (±4 notes) / Global (full piece) | Global + hierarchical | phrasing 需要长程 |
| **Pedal 建模** | Independent / Note-conditioned | Note-conditioned | 踏板与音符紧密相关 |

### 损失函数设计：多维度联合优化

```
Total Loss = L_timing + L_velocity + L_duration + L_pedal + L_structure

L_timing:      MSE(Δonset_pred, Δonset_target)  或 Huber loss
L_velocity:    MSE(velocity_pred, velocity_target) 或 ordinal cross-entropy
L_duration:    MSE(ratio_pred, ratio_target)
L_pedal:       BCE(pedal_pred, pedal_target)
L_structure:   乐句级别的 consistency loss（鼓励 phrase arc 的合理性）
```

**多模态处理：预测 (μ, σ, π) 而非单值**
```
p(Δonset | note) = Σ_k π_k · N(μ_k, σ_k)
```

### 训练策略：三层混合架构

> **关键架构决策**：风格数据主要来自 audio 而非 expressive MIDI。直接 AMT→MIDI 会破坏要学习的表达信息，纯 audio 监督又太弱。采用三层混合方案：

```
┌─────────────────────────────────────────────────────┐
│ Layer 1: 核心 Performance Model (MIDI-based)         │
│   训练数据: MAESTRO (aligned performance MIDI)        │
│   方法: 直接监督学习 Δonset, Δvel, duration, pedal    │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ↓            ↓            ↓
┌─────────────┐ ┌────────────┐ ┌─────────────────┐
│ Layer 2:     │ │ Layer 3:   │ │ Style Adapter   │
│ Audio 弱监督 │ │ AMT 辅助   │ │ (少量 MIDI)     │
│ 全局特征     │ │ 扩大数据   │ │ 微调风格        │
│             │ │             │ │                 │
│ Audio →     │ │ Audio →    │ │ 10-20首某钢琴家 │
│ tempo curve │ │ MIDI →     │ │ 的 aligned MIDI │
│ loudness    │ │ 对比校验   │ │ → 学个人风格     │
│ phrase boundary│            │ │                 │
└─────────────┘ └─────────────┘ └─────────────────┘
```

| 层 | 作用 | 数据需求 | 解决什么 |
|---|------|---------|---------|
| **Layer 1 (MIDI 主模型)** | 学"怎么弹" | MAESTRO 200h aligned MIDI | 基础 performance 能力 |
| **Layer 2 (Audio 弱监督)** | 提供全局轮廓 | 任意 piano audio (海量) | phrasing、tension/release 等长程结构 |
| **Layer 3 (Style Adapter)** | 个性化风格 | 少量 aligned MIDI (10-50首) | 特定钢琴家的 style |

**Layer 2 的关键设计**：
- 不需要 AMT——tempo curve、loudness envelope、phrase boundary 等全局特征可直接从 audio 提取（onset detection、energy contour）
- 音频监督是 **sequence-level** 的：模型输出的 performance MIDI 合成 audio 后，与目标 audio 在全局特征上对比（tempo RMSE、动态相关性），不是 note-by-note
- 可微分音源（DDSP-style piano synthesizer）提供端到端的 audio-level loss

**分阶段训练流程**：
1. **Phase 1 预训练（MAESTRO → Layer 1）**：Score → Performance mapping，全量数据，基础 timing + dynamics + pedaling
2. **Phase 2 多风格 fine-tuning（Layer 3）**：区分不同钢琴家/时期的演奏风格，conditioning on "style" vector
3. **Phase 3 Audio 弱监督微调（Layer 2）**：强化 phrase-level modeling，用 audio-level loss 校准全局表达轮廓

### 双向任务：同一个模型，两个方向

> **核心设计：Perform-LM 同时学习 Score→Performance（正向）和 Performance→Score（反向）。两套任务共享底层表征，只是输入/输出方向互换。**

```
正向（渲染）:  ABCX (纯净乐谱) → MIDI-TSV (演奏表达)
反向（解析）:  MIDI-TSV (演奏表达) → ABCX (纯净乐谱)
```

#### 为什么双向训练有效

| 维度 | 正向（Score→Performance） | 反向（Performance→Score） |
|------|--------------------------|--------------------------|
| **学习目标** | 给定"弹什么"，预测"怎么弹" | 给定"怎么弹"，还原"弹什么" |
| **输出空间** | 连续（Δonset, velocity, duration, pedal） | 离散（pitch, quantized onset/duration） |
| **问题性质** | 一对多（同一乐谱无数种演奏） | 多对一（不同演奏对应同一乐谱） |
| **训练难度** | 高（需学分布/风格） | 低（输出空间确定、可验证） |
| **共享知识** | ← 和声、曲式、乐句结构、风格直觉 | ← 同样的音乐结构理解 |

**共享的底层能力**：
- 和声分析：知道"这里是属七和弦"，正向用来决定 tension，反向用来验证 notes
- 曲式识别：知道"这里是再现部"，正向用来设计 crescendo，反向用来确认结构边界
- 乐句感知：知道"这里是一个乐句的结尾"，正向用来做 rallentando，反向用来检测 phrase boundary
- 风格直觉：知道"肖邦的 rubato 风格"，正向用来生成，反向用来识别
- Pedal 逻辑：知道"和声变化 → 换踏板"，正向用来预测，反向用来清理噪声

**反向任务比正向容易得多**——输出空间是离散的、可验证的。这使它成为极佳的"反向校验"：模型学会"理解演奏"之后，反过来帮助它"生成更好的演奏"。

#### 格式对应：ABCX ↔ MIDI-TSV

```
ABCX (Score)                          MIDI-TSV (Performance)
──────────────────────────────────   ──────────────────────────────────
X: 调号/拍号/速度标记                 保留所有 meta 信息
K: C                                 tempo / time_signature / key_signature
M: 4/4
L: 1/8
Q: 1/4=120
                                       每个音符的 micro-timing (tick scale)
音符: C4  →  C'                       pitch + 精确 onset tick + 精确 duration tick
时值: 1/8 →  精确量化网格              （不是网格值，是原始 tick）
力度: 无意义/固定                      velocity: 每个 note 独立值
踏板: 无                              P 记录: 每个 pedal event 的 tick + 值

示例 ABCX:                            对应 MIDI-TSV note:
V:1                                   C'    142    96    78
C'1/8                                  ↑     ↑      ↑     ↑
                                       pitch onset  dur   velocity
                                       （tick=10ms 级别精度）
```

#### 双向训练的数据流

```
┌─────────────────────────────────────────────────────────────┐
│  配对数据 (MAESTRO 200h)                                     │
│                                                              │
│  performance.mid                                             │
│    ├── quantize → Score MIDI → ABCX  ← 正向输入 / 反向输出    │
│    └── midi2tsv → MIDI-TSV        ← 正向输出 / 反向输入       │
│                                                              │
│  训练时混合两个方向：                                         │
│    正向样本: {input: ABCX, target: MIDI-TSV}                 │
│    反向样本: {input: MIDI-TSV, target: ABCX}                 │
└─────────────────────────────────────────────────────────────┘
```

#### Bootstrapping 数据飞轮：用模型降低数据获取成本

> **问题**：MAESTRO 仅 ~1,278 首古典钢琴，想扩展到流行/现代风格，但缺乏配对数据。
>
> **方案**：用训练好的模型自动从大量无配对 performance MIDI 中提取 score，形成新配对。

```
                    ┌──────────────────────────────────────┐
                    │         Step 1: 初始配对训练          │
                    │   MAESTRO 200h ABCX ↔ MIDI-TSV 双向   │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │  Step 2: 批量解析（反向任务应用）      │
                    │  大量无配对的 performance MIDI         │
                    │  (Lakh MIDI, Pop909, 网上MIDI库)      │
                    │         ↓                             │
                    │  模型: MIDI-TSV → 预测 ABCX           │
                    │  （反量化：从 rubato/timing 噪声中      │
                    │         恢复纯净乐谱）                  │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │  Step 3: 人工审核 ABCX                │
                    │  审核任务（非创作任务）：               │
                    │  - 音符对不对？                        │
                    │  - 节奏对不对？                        │
                    │  - 调号/拍号对不对？                   │
                    │                                      │
                    │  成本: 创作任务的 1/10 ~ 1/50          │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │  Step 4: 新配对加入 SFT 迭代           │
                    │  ABCX (审核后) + MIDI-TSV (原始)       │
                    │         → 高质量新配对数据             │
                    │         → 重新训练/增量微调            │
                    └──────────────┬───────────────────────┘
                                   │
                          回到 Step 2，循环放大
```

**为什么人工审核 ABCX 比人工创作 MIDI-TSV 便宜得多**：

| | 审核 ABCX（反向） | 创作/修改 MIDI-TSV（正向） |
|--|--|--|
| 任务性质 | 判断：音符对不对？ | 创作：每个 note 决定 velocity/timing |
| 操作 | 改几个错的音符 | 逐个音符调力度曲线、rubato、pedal |
| 工具 | 文本编辑器/乐谱查看器 | DAW piano roll，逐轨编辑 |
| 时间/曲 | ~2-5 分钟（简单流行钢琴） | ~30-120 分钟 |
| 难度 | 确定性高，容易判断 | 主观性强，没有"正确答案" |

**反向任务的关键优势：输出可验证。** 一个音符要么对要么错，审核者不需要"感觉好不好"，只需要"对不对"。这使得数据标注成本大幅降低，bootstrapping 飞轮可以高效运转。

#### 风格扩展路线

| 阶段 | 数据来源 | 风格覆盖 | 数据获取方式 |
|------|---------|---------|-------------|
| P0 | MAESTRO | 古典钢琴（Disklavier 录制） | 天然配对 |
| P1 | Yamaha e-Piano Competition | 古典钢琴（不同钢琴家） | 天然配对 |
| P2 | Lakh MIDI（流行/摇滚钢琴编配） | 流行钢琴、多风格 | Step 2-4 bootstrapping |
| P3 | Pop909 + 网上 MIDI 库 | 现代流行钢琴 | Step 2-4 bootstrapping |
| P4 | 用户/社区贡献 | 任意风格 | 持续积累 |

---

## 七、任务定位：这是 EPR 吗？

> **短答：不是传统意义上的 EPR。**
> 我们做的是 **Bidirectional Symbolic-Performance Translation**（双向符号-表演翻译）——EPR 的一个 LLM-native 变体 + 一个 EPR 从未触及的反向任务。

### 与传统 EPR 的本质区别

| 维度 | 传统 EPR（Peransformer, VirtuosoNet, Dexter, ScorePerformer） | 本研究 |
|------|-----------------------------------------------------------|--------|
| **输入格式** | Score MIDI（pitch, onset, duration, constant velocity） | **ABCX**（符号乐谱：调号、拍号、连音线、装饰音、Ped. 标记、强弱术语） |
| **输出格式** | Performance MIDI（预测 Δonset, Δduration, velocity, pedal） | **MIDI-TSV**（文本化表演描述）→ 再转 MIDI |
| **模型架构** | Transformer encoder + regression head | **LLM**（next-token prediction） |
| **学习范式** | 回归 / 分布预测 / 分类 | 语言生成 |
| **方向** | 单向 Score → Performance | **双向 ABCX ↔ MIDI-TSV** |
| **反向任务** | 不存在（少数有 discriminator 作为辅助，但不是生成器） | **核心设计目标之一** |

### 三个根本性差异

**差异 1：输入表示层次更高。** 传统 EPR 的 score MIDI 信息量极少——只有 pitch、onset、duration，连 "p/f" 都没有。而 ABCX 保留了 MusicXML 级别的符号语义：谱面上的 `p`、`crescendo`、`Ped./✻`、`staccato`、`legato`、`tr` 都是显式的 token。这意味着"演奏者视角"的规则性知识（参见第二节 Pedaling 的讨论）可以被模型直接读取，而不是从 MIDI 中"猜"出来。

**差异 2：生成范式不同。** LLM 做 next-token prediction，天然擅长"风格一致性"和"长程结构"（phrasing 是跨 8-32 小节的，恰好是 Transformer 的优势区间）。传统 EPR 的 regression 模型容易预测"平均演奏"，而 LLM 的采样机制（temperature, nucleus）天然支持"一对多"的多样性输出。

**差异 3：反向任务是新领域。** 没有任何现有 EPR 论文做"从 expressive performance 恢复干净 score"。Peransformer 的 discriminator 是"真/假"二分类，不是生成器。你的反向任务（Performance → Score）是：
- **EPR 领域的空白**
- **数据飞轮的核心引擎**（参考第六节 Bootstrapping）
- **独立可评估的任务**（输出是离散的、可验证的，人工审核成本低）

### 如何与现有 EPR 方法比较

应当**分层对比**，不要硬塞到 "EPR benchmark" 框架里：

**Layer A：演奏质量（与 EPR 共享的 benchmark）**
- 指标：timing RMSE、velocity Pearson correlation、KLD、DTWD、人类盲听 MOS
- 对比对象：Peransformer、VirtuosoNet、Dexter、ScorePerformer
- 数据集：ASAP、ATEPP subset B、MAESTRO
- 预期：LLM 可能在小数据下不如 regression 模型，但在 zero-shot / 跨风格场景应该有优势

**Layer B：数据效率（LLM 的传统优势区）**
- 指标：few-shot performance、zero-shot cross-style generalization
- 对比对象：从头训练的 Transformer EPR
- 数据集：ATEPP subset A / IMSLP 扩展数据
- 如果 LLM 的预训练携带了音乐常识（乐理、和声分析），这里应该有显著优势

**Layer C：独特能力（EPR 文献空白）**
- 任务：Performance → Score recovery
- 指标：score accuracy（pitch）、rhythm reconstruction F1、调号/拍号识别准确率
- 对比对象：无直接对照——这是**新任务**
- 次要对比：MT3（Multi-Task Transcription）等音频 transcription 工作，但它们任务不同

### 论文定位建议

**不要把论文 pitch 成"另一个 EPR 系统"**——会陷入与 Peransformer/Dexter 在 Layer A 上的苦战，且可能没有 SOTA 优势。

**更好的 pitch**：
- 主题：**Bidirectional symbolic-performance translation as a pre-training objective for music understanding**
- 创新点 1：Novel dual-direction task formulation
- 创新点 2：ABCX 作为 score representation（比 MIDI 信息量更大）
- 创新点 3：Bootstrapping 数据飞轮（反向任务自动生成训练对）
- 创新点 4：LLM 作为 performance generator（不是传统 regression）

与传统 EPR 的关系：**"EPR is one of the downstream tasks we support"**——而不是"we are a new EPR method"。

---

## 八、数据集构建：最大的现实障碍

> **数据集获取本身就是一个独立的研究问题，成本可能占整个项目的 40-60%。**
> 这是项目的最大风险，也是最大机会——如果能做出一个高质量的 aligned 三元组数据集，本身就有独立发表价值。

### 所需数据的本质：ABCX ↔ MIDI 三元组

```
理想的训练样本 =
    (ABCX score 乐谱, Score MIDI, Performance MIDI)
```

三者需要严格对齐，这是目前**没有任何公开数据集**完整覆盖的。现状：

| 数据集 | ABCX | Score MIDI | Performance MIDI | 备注 |
|--------|------|-----------|-----------------|------|
| ASAP | ❌ | ✅ 235 | ✅ 1067 | 需构造 ABCX |
| MAESTRO v3 | ❌ | ❌ | ✅ 1276 | 需同时构造 ABCX + Score MIDI |
| ATEPP | ❌ | ❌ | ✅ 1497 | 需同时构造 ABCX + Score MIDI |
| GiantMIDI | ❌ | ❌ | ✅ 10,853 | 反向任务的 bootstrapping 目标 |
| Pianist8 | ❌ | ❌ | ✅ 411 | 现代钢琴家，版权受限 |
| EMOPIA | ❌ | ❌ | ✅ 1071 | 流行钢琴，版权问题严重 |

### 数据源 A：ASAP 的 ABCX 构造

**现状**：已跑通 `midi_to_abcx.py`，235 首 `midi_score.mid` → 235 个 ABCX，`abc2abcx.py` 全部验证通过。

**但这只是"初级 ABCX"**。Score MIDI → ABCX 是**有损的**：
- ✅ 保留：pitch、rhythm、bar/beat、key、time signature
- ❌ 丢失：`p/f/ff` 强弱术语、`crescendo/diminuendo` 渐变符号、`slur` 连音线、`staccato` 点、`Ped./✻` 踏板标记、`rit./accel.` 速度指示、装饰音符号

这些丢失的正是 EPR 最需要的"演奏者视角的规则性信息"（见第二节）。

**改进路径**：
1. **首选方案：MusicXML → ABCX**（ASAP 有 222 个 MusicXML score！）
   - MusicXML 保留了所有谱面信号
   - 需要写/扩展 `musicxml_to_abcx.py`（目前只有 `midi_to_abcx.py`）
   - 这是**一周工作量**，产出的 ABCX 质量会显著提升

2. **次选方案：LLM 反推**
   - 给 LLM 输入 MIDI 特征 + 初级 ABCX，让它补充表达标记
   - 风险：LLM 会"幻觉"出谱面没有的标记
   - 只适合作为初级 ABCX 的 fallback

**结论**：**必须先实现 MusicXML → ABCX**，否则整个项目的"ABCX 信息量 > score MIDI"的核心优势会被这一步稀释掉。

### 数据源 B：MAESTRO/ATEPP/GiantMIDI 的乐谱获取

**问题**：这些数据集**没有提供对应的 MusicXML / ABCX 乐谱**。必须自己构造。

**路径 1：基于 performance MIDI 反推 score**（本研究的反向任务本身）
- 自动 quantize（Nakamura alignment + music21）→ 初级 score MIDI
- MIDI → ABCX（现有管线）→ 初级 ABCX
- 人工审核（参考第六节 bootstrapping）

**路径 2：外部乐谱数据库匹配**

| 数据源 | 规模 | 访问性 | 格式 | 法律状态 |
|--------|------|-------|------|---------|
| **MuseScore Community** | ~数百万 | 需 API / 手动下载，受限 | MSCX / MIDI | 用户上传，版权混乱 |
| **IMSLP** | ~60 万 | 公开 | PDF（需 OMR） / MusicXML（少量） | 公有领域为主 |
| **Mutopia Project** | ~2 千 | 公开 | LilyPond | 公有领域，CC 许可 |
| **DCML Corpora** | ~数百 | 公开 | MuseScore + harmonic annotations | CC-BY-NC-SA |
| **OpenScore** | ~数千 | 公开 | MuseScore | 公有领域 |
| **CCARH Humdrum** | ~数千 | 公开 | Humdrum (**kern) | 公有领域 |

**MAESTRO 匹配策略**：
- MAESTRO 的 CSV 有 `canonical_composer` + `canonical_title`
- 按"composer + title"在 MuseScore Community / IMSLP 匹配
- 但 MAESTRO 的曲目大多是古典奏鸣曲（Beethoven Op.XX No.Y, Chopin Ballades, ...），**这些都在公有领域**
- **预期匹配率**：Bach/Mozart/Beethoven/Chopin/Schubert/Schumann/Liszt → 70-90%
- **难点**：作曲家少见的变体版本、不同版本的 repeat 处理、cadenza 差异

### 数据源 C：版权问题的分层评估

这是**必须正面面对**的问题。分三层：

**Layer 1：公有领域（Public Domain）—— 安全**
- 作曲家去世满 70 年（或美国 1928 年前发表）
- 覆盖范围：Bach, Mozart, Haydn, Beethoven, Schubert, Chopin, Schumann, Liszt, Brahms, Debussy (大部分), Ravel (大部分), Prokofiev (早期作品), Rachmaninoff (早期作品), Scriabin, Balakirev
- **ASAP 的 14 位作曲家几乎全在此列** ✅
- **MAESTRO 的主体曲目（古典奏鸣曲）也在此列** ✅
- **GiantMIDI 的 2786 位作曲家主体是古典** ✅

**Layer 2：录音版权 vs. 作品版权（复杂）**
- 作品本身（曲谱）公有领域，但**特定录音的版权**属于演奏者/唱片公司
- MIDI transcription（从录音提取）的法律地位：灰色地带
  - 美国：2014 年 *Capitol Records v. ReDigi* 后，音频-to-MIDI 被部分法院视为衍生作品
  - 但学术数据集（MAESTRO、ATEPP、GiantMIDI）均以 "research-only" 名义分发，引用时注明 CC-BY-NC 等许可
- **建议**：数据集发布时使用 CC-BY-NC-SA，明确"research use only"

**Layer 3：现代流行音乐（版权受限）—— 谨慎**
- ❌ Pianist8：Yiruma、Einaudi、Clayderman arrangements、Hancock、Sakamoto、Hisaishi、Bethel/Hillsong → **全部受版权保护**
- ❌ EMOPIA：现代流行歌曲的钢琴改编 → **版权风险高**
- **如果最终数据集要公开发布**，这两部分只能：
  - 提供 **metadata + 下载脚本**（让用户自己从源获取）
  - 或只发布**模型权重 + 评估代码**（不分发原始数据）

### 数据集构建的实际工作量估算

| 任务 | 工作量 | 难度 | 风险 |
|------|-------|------|------|
| `musicxml_to_abcx.py` 实现 | 1 周 | ⭐⭐⭐ | 低 |
| ASAP（235 曲）MusicXML → ABCX | 1 天（自动） | ⭐ | 低 |
| ASAP ABCX 人工审核 | 2-3 周（1 人） | ⭐⭐ | 中 |
| MAESTRO 曲目在 MuseScore/IMSLP 匹配 | 2-4 周（含爬虫） | ⭐⭐⭐⭐ | 高（匹配失败率） |
| PDF OMR（IMSLP 扫描版） | 4+ 周 | ⭐⭐⭐⭐⭐ | 很高（OMR 准确率） |
| Pianist8 的反向任务 bootstrapping | 2-3 周 | ⭐⭐⭐ | 中 |
| 版权审查与许可选择 | 1 周 | ⭐⭐ | 中（法律问题） |
| **总计** | **~3-4 个月（单人）** | | |

### 数据集本身作为独立研究产出

> **是的，这个数据集有独立发表价值，甚至可能比方法论文更容易发表。**

**可对标的数据集论文**：
- **ATEPP** (ISMIR 2022)：~11,700 performances 的 transcribed MIDI，没有 score 对齐，仅凭"规模大 + automation"就被 ISMIR 接收
- **ASAP** (ISMIR 2020)：235 scores + 1067 performances + beat alignment，发表并被广泛引用
- **MAESTRO** (ICLR 2019)：200h performance MIDI + audio，成为领域基础设施

**本数据集的独特价值**：
1. **Aligned 三元组**：ABCX + Score MIDI + Performance MIDI，**领域首个** symbolic 层完整的 piano 数据集
2. **ABCX 的文本特性**：可以直接用于 LLM 训练，MusicXML/MIDI 无法做到
3. **规模**：如果覆盖 MAESTRO + ASAP + ATEPP，预期 **~3,000 对齐三元组**（对 symbolic music 而言是中等规模）
4. **双向配对**：正向和反向任务共享同一数据集

**可投稿venue**：
- **TISMIR**（Transactions of ISMIR）：接收 dataset papers，是首选
- **ISMIR 会议 Dataset track**：年度 dataset papers
- **NeurIPS Datasets & Benchmarks**：更 ML 导向，规模要求更高
- **Zenodo + arXiv preprint**：纯数据集发布，不走传统会议

**建议发表策略**：
```
Year 1 Q1-Q2:  MusicXML→ABCX 工具 + ASAP 数据集（首发，1000 对齐样本）
Year 1 Q3-Q4:  扩展到 MAESTRO / ATEPP，发布 v2（3000+ 样本）  
              → 投 ISMIR/TISMIR dataset paper
Year 2:       双向模型论文
              → 投 ISMIR method paper 或 ICLR
```

**数据集论文的优势**：
- 审稿人评价标准明确（规模、质量、许可、文档）
- 不需要超过现有方法的 SOTA 指标
- 一旦发布，成为领域基础设施，引用量持续增长
- 让后续方法论文更有说服力（"we use our dataset"）

### 结论与行动项

**数据集构建是项目的首要工作，优先级高于模型训练。** 具体行动：

1. **立即启动**：`musicxml_to_abcx.py` 实现（利用 ASAP 的 222 个 MusicXML）
2. **短期**（1-2 月）：ASAP v1 发布 - 222 (ABCX, Score MIDI, Performance MIDI) 三元组
3. **中期**（3-4 月）：MAESTRO 曲目匹配 MuseScore Community / IMSLP，扩展数据集到 1000+ 样本
4. **长期**（6 月+）：用训练好的反向模型 bootstrap GiantMIDI，扩展到 3000+
5. **并行**：版权审查 + 数据集许可选择（CC-BY-NC-SA 推荐）

---

## 九、核心挑战与应对策略

### 一对多问题：同一 Score 有无数种演奏

**应对**：
1. **预测分布而非单值**：GMM / VAE / Diffusion
2. **Style conditioning**：通过 latent vector 控制演奏风格
3. **Multi-pianist 数据**：让模型学习不同演奏家的特点

### 连续 vs 离散：Timing 是 ms 级的，但 Transformer 擅长离散 token

**应对**：
- 使用 **continuous tokenization**：将连续值映射到 learned embedding
- 或使用 **mixture density network (MDN)** head：直接输出连续分布参数

### 长程依赖：Phrase shaping 跨越 8-32 小节

**应对**：
- **Hierarchical modeling**：phrase-level → note-level 两层
- **External structure input**：预计算乐句边界、和声分析作为条件
- **Long-context Transformer**：使用 FlashAttention / Ring Attention

### 评估难题：如何量化"演奏质量"

| 指标 | 计算方式 | 说明 |
|------|---------|------|
| **Timing RMSE** | RMS(Δonset_pred - Δonset_target) | 直观但过于机械 |
| **Velocity correlation** | Pearson corr(vel_pred, vel_target) | 捕捉动态轮廓 |
| **Perceptual test** | 人类盲听评分 | 最终标准但成本高 |
| **MUSEScore / FRAP** | 专用音乐性能评估框架 | 学术标准 |
| **Style transfer accuracy** | 分类器能否识别目标演奏家 | 风格保真度 |

---

## 十、落地路径：从 Score 到顶级音源的完整 Pipeline

### 完整处理流程

```
用户输入
  ├── PDF 乐谱 → OMR (Audiveris / Photoscore) → MusicXML
  ├── MusicXML → 提取音符 (pitch, onset, duration)
  └── 或直接提供 Score MIDI

Piano Performance Model
  ├── Score Encoder → context-aware note representation
  ├── Performance Decoder → (Δonset, Δdur, vel, pedal, articulation)
  └── 输出: Expressive Performance MIDI

音源合成
  ├── Yamaha CFX / Disklavier sound library
  ├── Logic Pro (Steinway D / Grand Piano)
  ├── Pianoteq (物理建模)
  └── SampleModeling / Keyscape
  ↓
最终音频（WAV/MP3）
```

### MIDI 输出规范：为顶级音源优化

```
✅ 高精度 timing：ticks 或 seconds（避免 16 分音符网格量化）
✅ 连续 velocity：0-127 整数，保留动态梯度
✅ Pedal CC64：包含半踏板值（不只是 0/127）
✅ 每 note 精确的 note-off timing（articulation 关键）
✅ 可选：CC1 (Modulation) for expressiveness
✅ 可选：CC11 (Expression) for phrase-level dynamics
```

### 音源推荐

| 音源 | 类型 | 特点 | 适用场景 |
|------|------|------|---------|
| **Yamaha CFX / S900** | 采样 | 音乐会三角钢琴，真实感强 | 古典录音 |
| **Pianoteq** | 物理建模 | 响应灵敏，参数可调 | 实时演奏/实验 |
| **Logic Pro Steinway D** | 采样 | Apple 内置，质量高 | 快速预览 |
| **Keyscape** | 采样 | 多款经典钢琴，音色丰富 | 多样化需求 |
| **Garritan CFX** | 采样 | 免费选项 | 测试/原型 |

---

## 十一、实施计划：分阶段的现实路线

### Phase 1: 数据准备与探索（1-2 周）

- [ ] 下载 MAESTRO v3.0，探索数据结构
- [ ] 实现 Score 提取（从 performance MIDI 反推 quantized score）
- [ ] 计算 performance deviation 统计（timing, velocity 分布）
- [ ] 探索 ASAP 数据集（有更干净的 score 对齐）

### Phase 2: Baseline 模型（2-3 周）

- [ ] 实现 note-level 回归 baseline（简单 MLP / LSTM）
- [ ] 输入：local context window (±4 notes)
- [ ] 输出：Δonset, Δvelocity
- [ ] 评估：与 ground truth 的 RMSE + 盲听测试

### Phase 3: Transformer 模型（3-4 周）

- [ ] Score-conditioned Transformer
- [ ] Global context + hierarchical structure
- [ ] 多模态输出（GMM head）
- [ ] Pedal modeling

### Phase 4: 风格化与长程结构（4-6 周）

- [ ] Style conditioning（latent vector / pianist ID）
- [ ] Phrase-level modeling（外部结构注入）
- [ ] 完整 pipeline 集成（Score → MIDI → 音源）

---

## 十二、关键参考文献

### 核心论文

| 论文 | 年份 | 要点 |
|------|------|------|
| [Performance RNN: Generating Music with Expressive Timing and Dynamics](https://magenta.tensorflow.org/performance-rnn) | 2018 | Google Magenta，expressive control token |
| [The Musical Performance Synthesis](https://arxiv.org/abs/1907.07542) (Hawthorne et al.) | 2019 | Piano Tree，seq2seq performance |
| [Exploring Basic Rules of Music Expression](https://www.kth.se) (Widmer) | 2000s | KTH 规则集，经典传统方法 |
| [ASAP: Aligned Scores and Performances](https://archives.ismir.net/ismir2019/paper/000056.pdf) | 2019 | 对齐的 score-performance 数据集 |
| [MAESTRO Dataset](https://arxiv.org/abs/1810.12247) (Hawthorne et al.) | 2018 | 200h 钢琴 MIDI+audio |

### 相关研究方向

| 方向 | 要点 |
|------|------|
| **Automatic Music Performance** | 从乐谱自动生成演奏 |
| **Score Following** | 实时跟踪演奏进度 |
| **Expressive Rendering** | 乐谱→演奏表达的传统方法 |
| **Style Transfer for Performance** | 将一位演奏家的风格迁移到另一首曲子 |

---

## 十三、Insight 日志

> 随着研究推进，将新的认知记录在此。

| 日期 | 洞察 |
|------|------|
| 2026-04-21 | **从 Music Generation 到 Performance Model 的关键转变**：前者是"创造什么"（高创造性、高不确定性），后者是"怎么弹"（低创造性、高可评估性）。这个转变大幅缩小了问题空间，使得在有限数据下取得有意义的结果成为可能 |
| 2026-04-21 | **Performance 不是"噪声"而是"信号"**：传统方法将 timing deviation 视为对网格的偏差，但实际上它是系统性的、结构化的、可学习的音乐表达 |
| 2026-04-21 | **顶层音源的质量取决于输入 MIDI 的质量**：再好的音源也无法拯救量化的、机械的 MIDI。Performance Model 的价值在于让现有顶级音源发挥全部潜力 |
| 2026-04-21 | **这是一个未被大部队占领的方向**：ISMIR 每年只有 3-8 篇相关论文，大厂投入几乎为零。当前 SOTA 仍处于 Level 3（人类 60-70% 能分辨），离 Level 5 有明显差距——这既是问题，也是机会 |
| 2026-04-21 | **效果瓶颈的根源不在模型容量**：当前方法的主要问题是数据量不足（200h vs 30 万小时）、一对多未解决（模型学的是"平均演奏"而非分布）、缺少高层音乐知识（不懂"这里是高潮"） |
| 2026-04-21 | **难度 = 1/(谱面信息密度 + 规则明确度)**：pedaling 被学术文献列为"最薄弱环节"，但从演奏者视角，它反而是最容易的——因为和声变化驱动换踏板是明确规则。真正难的是 rubato 和 phrasing，谱上没有精确标记，靠演奏者直觉 |
| 2026-04-21 | **风格迁移的核心矛盾：钢琴家的风格数据是 audio，不是 expressive MIDI**。纯 AMT→MIDI 会破坏表达信息，纯 audio 监督又太弱。解决方案是三层架构：Layer 1 (MIDI 主模型) + Layer 2 (audio 弱监督提取全局轮廓) + Layer 3 (少量 aligned MIDI 做 style adapter) |
| 2026-05-02 | **本项目不是传统 EPR，而是 Bidirectional Symbolic-Performance Translation**：传统 EPR 是 Score MIDI → Performance MIDI 的 regression；本项目是 ABCX ↔ MIDI-TSV 的 LLM 双向生成。核心区别是输入表示层次更高（ABCX 保留谱面符号语义）、生成范式是 LLM 而非 regression、反向任务是 EPR 文献空白 |
| 2026-05-02 | **MIDI score → ABCX 是有损的，必须用 MusicXML → ABCX 才能发挥 ABCX 的信息量优势**：score MIDI 丢失了 `p/f`、`crescendo`、`slur`、`Ped.`、`rit.` 等所有表达标记，这些恰好是"演奏者视角的规则性信息"。ASAP 有 222 个 MusicXML，必须优先实现 `musicxml_to_abcx.py`，否则 ABCX 退化成 score MIDI 的等价表示，项目核心优势消失 |
| 2026-05-02 | **数据集本身可能比方法论文更先值得发表**：对标 ATEPP/ASAP/MAESTRO 的成功案例，一个 aligned (ABCX, Score MIDI, Performance MIDI) 三元组数据集是领域首次。投稿路线：TISMIR dataset paper → ISMIR method paper。版权上，ASAP/MAESTRO 的古典曲目全在公有领域，Pianist8/EMOPIA 的现代曲目只能通过 metadata + 下载脚本的形式间接分发 |
| 2026-05-02 | **数据集构建工作量是 3-4 人月**：MusicXML→ABCX 实现 (1 周) + ASAP 审核 (2-3 周) + MAESTRO 在 MuseScore/IMSLP 匹配 (2-4 周) + OMR (4+ 周) + bootstrapping (2-3 周) + 版权审查 (1 周)。这个工作量超过很多方法论文的实现成本，但一次做对可以持续复利 |

---

## 附录：与主研究的交叉引用

| 本文档                          | 主文档 ([[Music Generation研究]])            |
| ---------------------------- | --------------------------------------- |
| 本节 = Score→Performance 的具体实现 | 第九节 = Score vs Performance 的理论区分        |
| 本节 = 数据与模型选择                 | 第十节 = 两阶段方案的 Stage 2                    |
| 本节 = 连续参数回归                  | 第十二节 Q2 = "如何在 Transformer 中表达区间作用"     |
| 本节 = Phrasing 建模             | 第十二节 Q4 = "既能 symbolic 又能表达 nuance 的表示" |
