# SPIRE SFT 设计

## 1. 核心问题：CPT 还是 SFT？

### 1.1 判断标准

- **目标决定方法**：如果目标是论文任务效果（score→performance、format conversion），SFT 优先；如果目标是训练一个音乐文本基础模型（通用补全、续写、风格迁移），CPT 更必要。
- **SFT 可替代 CPT 的三种情况**：
  1. 基础模型已有较强的代码/表格/结构化文本能力（MIDI-TSV、ABCX 本质是结构化文本）
  2. 目标任务明确（score→performance、format conversion、repair）
  3. 能构造大量高质量任务样本
- **SFT 不能替代 CPT 的情况**：模型完全不熟悉表示语言；大量无标注数据但配对数据少；需要通用领域补全能力；SFT 数据覆盖不足。

### 1.2 实验驱动的训练策略

**核心问题**：Language Learning SFT 是否必要？Measure-level 还是 Phrase-level？

**实验设计**：通过对比实验验证不同训练路径的效果（详见 [第 9 节](#9-实验设计与评估)）。

**两种可能的训练路线**：

```
路线 A：直接 EPR
Base LLM → EPR SFT → spire-sft-epr

路线 B：Language Learning → EPR
Base LLM → Language Learning SFT → EPR SFT → spire-sft-epr
```

**粒度选择**：
- Measure-level (M)：小节级，输入输出短，训练稳定
- Phrase-level (H)：乐句级（4-8 小节），context 更长，可能表达性更好

**V1 实验目标**：
1. 验证 Language Learning 是否有帮助（路线 A vs 路线 B）
2. 验证粒度选择的影响（Measure vs Phrase）
3. 根据实验结果决定最终训练策略

关键原则：

1. **先做实验，再定策略**：不预设 Language Learning 必要性，用数据说话
2. **粒度独立实验**：Measure-level 和 Phrase-level 分别实验，不混合
3. **EPR 优先，CSR 后置**：V1 只做 EPR，CSR 作为 V2 目标
4. **最小化实验成本**：V1 只训练 4 个核心模型，快速验证假设

### 1.3 评估基线

先做小规模 SFT 实验（1–3 epoch），根据错误类型判断是否需要 CPT：

| 主要错误类型 | 说明 |
|---|---|
| 格式崩、token 不认识、长序列结构断裂 | 需要 CPT 或 SFT 化 CPT |
| 任务理解错、输出风格不稳定 | 加强 SFT 即可 |

评估指标：parse success rate、measure duration consistency、event validity、ABCX ↔ MIDI-TSV match、score-performance alignment metric、OOD 泛化。

---

## 2. 符号体系

### 2.1 大写：语言/集合

| 符号 | 含义 |
|---|---|
| $\Sigma$ | 乐谱语言 / 乐谱集 |
| $\Phi$ | 演奏语言 / 演奏集 |

### 2.2 小写：具体样本

| 符号 | 含义 |
|---|---|
| $\sigma \in \Sigma$ | 一首具体乐谱 |
| $\phi \in \Phi$ | 一次具体演奏 |
| $\sigma_{H_k}$、$\phi_{H_k}$ | 第 $k$ 个乐句（phrase） |
| $\sigma_{M_k}$、$\phi_{M_k}$ | 第 $k$ 个小节（measure） |
| $\sigma_{\text{head}}$ | 乐谱头部（调号、拍号、tempo、metadata 等） |
| $f(\cdot)$ | Score mask 函数，遮去乐谱的特定属性 |
| $g(\cdot)$ | Performance mask 函数，遮去演奏的特定属性 |

> 避免使用 H/P/M/S 作为抽象变量——它们在 MIDI-TSV 中已有具体含义（H=phrase, P=pedal, M=measure, S=slice）。也避免用 $\pi$ 表示 performance（RLHF 中常用作 policy model）。

### 2.3 Mask 函数定义

**Score mask $f$ 的变体：**

| 记号 | 遮去内容 | 示例 |
|---|---|---|
| $f_{\text{acc}}(\sigma)$ | 遮去所有升降号（#、b） | 调性推断 |
| $f_{\text{treble}}(\sigma)$ | 遮去高音谱声部 | 低音预测高音 |
| $f_{\text{bass}}(\sigma)$ | 遮去低音谱声部 | 高音预测低音 |
| $f_{\text{label}}(\sigma)$ | 遮去表情、力度、速度与演奏法标记，如 `p`、`f`、`acc.`、`rit.`、`Ped.`、staccato、slur 等 | 恢复谱面 expressive / articulation labels |

**Performance mask $g$ 的变体：**

| 记号 | 遮去内容 | 示例 |
|---|---|---|
| $g_{\text{timing}}(\phi)$ | 遮去 onset / timing | 学演奏时序推断 |
| $g_{\text{vel}}(\phi)$ | 遮去 velocity | 学力度表达推断 |
| $g_{\text{dur}}(\phi)$ | 遮去 note duration | 学 articulation 推断 |
| $g_{\text{pedal}}(\phi)$ | 遮去 pedal events | 学踏板策略推断 |

> Priority: **timing > velocity > duration > pedal**。pitch mask 不推荐——pitch 大多由 score 决定。

### 2.4 数据集定义

| 数据集 | 符号 | 说明 |
|---|---|---|
| 未配对乐谱集 | $\mathcal{D}_{\Sigma} = \{ \sigma^{(i)} \}_{i=1}^{N}$ | 仅有 score，无对应 performance |
| 未配对演奏集 | $\mathcal{D}_{\Phi} = \{ \phi^{(j)} \}_{j=1}^{M}$ | 仅有 performance MIDI，无对应 score |
| 小节级配对集 | $\mathcal{D}_{\Sigma\Phi}^{M} = \{ (\sigma_{M_k}^{(i)}, \phi_{M_k}^{(i)}) \}$ | score-performance 在 measure 级别对齐 |

> 不需要曲目级配对或乐句级配对。配对数据中如果 phrase 级对齐质量差，降级为未配对数据集用于 Language Learning SFT；只有对齐可靠的配对才用于 EPR / CSR SFT。

---

## 3. 任务体系

核心任务分为 4 大类：**Score Language**、**Performance Language**、**EPR**、**CSR**。

> **重要**：Measure-level 和 Phrase-level 任务是**独立的**，不混合。Measure Lang 只包含 Measure-level 任务，Phrase Lang 只包含 Phrase-level 任务。

### 3.1 Score Language

学习乐谱表示的语法、结构、乐句延续。

#### Measure-level Score Language

| 任务 | 公式 | 优先级 | 说明 |
|---|---|---|---|
| Measure continuation | $\sigma_{\text{head}} + \sigma_{M_k} \rightarrow \sigma_{M_{k+1}}$ | 高 | 学局部格式、measure boundary |
| Measure mask reconstruction | $\sigma_{\text{head}} + f(\sigma_{M_k}) \rightarrow \sigma_{M_k}$ | 高 | 用 $f$ 遮去部分信息后恢复 |

#### Phrase-level Score Language

| 任务 | 公式 | 优先级 | 说明 |
|---|---|---|---|
| Phrase continuation | $\sigma_{\text{head}} + \sigma_{H_k} \rightarrow \sigma_{H_{k+1}}$ | 高 | 学乐谱乐句延续、重复与变奏 |
| Phrase mask reconstruction | $\sigma_{\text{head}} + f(\sigma_{H_k}) \rightarrow \sigma_{H_k}$ | 高 | 用 $f$ 遮去部分信息后恢复 |

> $f$ 的具体变体见 [2.3 Mask 函数定义](#23-mask-函数定义)，包括 acc / treble / bass / label 等。

### 3.2 Performance Language

学习 performance MIDI 的事件分布、属性连续性。

#### Measure-level Performance Language

| 任务 | 公式 | 优先级 | 说明 |
|---|---|---|---|
| Measure continuation | $\phi_{M_k} \rightarrow \phi_{M_{k+1}}$ | 高 | 学局部演奏事件分布 |
| Measure mask reconstruction | $g(\phi_{M_k}) \rightarrow \phi_{M_k}$ | 高 | 用 $g$ 遮去某一类属性后恢复 |

#### Phrase-level Performance Language

| 任务 | 公式 | 优先级 | 说明 |
|---|---|---|---|
| Phrase continuation | $\phi_{H_k} \rightarrow \phi_{H_{k+1}}$ | 高 | 学 performance 分布 |
| Phrase mask reconstruction | $g(\phi_{H_k}) \rightarrow \phi_{H_k}$ | 高 | 用 $g$ 遮去某一类属性后恢复 |

> $g$ 的具体变体见 [2.3 Mask 函数定义](#23-mask-函数定义)，包括 timing / velocity / duration / pedal 等。

### 3.3 EPR：Expressive Performance Rendering

从 score 生成 expressive performance。

#### Measure-level EPR

| 任务 | 公式 | 优先级 | 说明 |
|---|---|---|---|
| **Measure EPR（主任务）** | $\sigma_{\text{head}} + \sigma_{M_{k-1}} + \sigma_{M_k} + \sigma_{M_{k+1}} \rightarrow \phi_{M_k}$ | **最高** | 3-measure context window，输出中间小节 |
| Cold-start EPR | $\sigma_{\text{head}} + \sigma_{M_1} + \sigma_{M_2} \rightarrow \phi_{M_1}$ | 高 | 曲子开头渲染（无前文） |
| EPR attribute generation | $\sigma_{\text{head}} + \sigma_{M_k} + g(\phi_{M_k}) \rightarrow \phi_{M_k}$ | 中 | 用 $g$ mask 生成 timing / velocity / duration / pedal 等演奏属性 |

#### Phrase-level EPR

| 任务 | 公式 | 优先级 | 说明 |
|---|---|---|---|
| **Phrase EPR（主任务）** | $\sigma_{\text{head}} + \sigma_{H_{k-1}} + \sigma_{H_k} + \sigma_{H_{k+1}} \rightarrow \phi_{H_k}$ | **最高** | 3-phrase context window，输出中间乐句 |
| Cold-start EPR | $\sigma_{\text{head}} + \sigma_{H_1} + \sigma_{H_2} \rightarrow \phi_{H_1}$ | 高 | 曲子开头渲染（无前文） |
| Intra-phrase EPR | $\sigma_{\text{head}} + \sigma_{H_k} + \text{partial } \phi_{H_k} \rightarrow \text{remaining } \phi_{H_k}$ | 中 | 长乐句内部续写（仅 Phrase-level 需要） |
| EPR attribute generation | $\sigma_{\text{head}} + \sigma_{H_k} + g(\phi_{H_k}) \rightarrow \phi_{H_k}$ | 中 | 用 $g$ mask 生成演奏属性 |

> Priority: **timing > velocity > duration > pedal**。pitch mask 不推荐——pitch 大多由 score 决定，不是 expressive performance 的主要难点。
> 
> **V1 简化**：只做主任务（Measure EPR 或 Phrase EPR），不做 attribute generation 和 intra-phrase EPR。

### 3.4 CSR：Canonical Score Reconstruction

从 performance 恢复规范 score。分两个阶段：先单乐句投票确定 head，再以 head 为条件重建 score phrase。

| 任务 | 公式 | 优先级 | 说明 |
|---|---|---|---|
| **Head prediction** | $\phi_{H_k} \rightarrow \hat{\sigma}_{\text{head}}^{(k)}$ | 高 | 每个乐句独立预测 head，多句投票得最终结果 |
| **Head-conditioned CSR** | $\hat{\sigma}_{\text{head}} + \phi_{H_k} \rightarrow \sigma_{H_k}$ | **最高** | 利用投票确定的 head 恢复乐句 |
| CSR attribute recovery | $\hat{\sigma}_{\text{head}} + \phi_{H_k} + f(\sigma_{H_k}) \rightarrow \sigma_{H_k}$ | 中 | 用 2.3 中定义的 $f$ mask 恢复 acc / treble / bass / label 等 score 属性 |

**Head prediction 的投票策略：** 每个乐句 $\phi_{H_k}$ 独立预测 $\hat{\sigma}_{\text{head}}^{(k)}$，对各字段（拍号、调号、tempo 等）分别投票取多数，得到最终 $\hat{\sigma}_{\text{head}}$。

**Attribute generation / recovery 与 EPR / CSR 对称：** EPR 用 $g$ mask 遮去 performance 属性并恢复，CSR 用 $f$ mask 遮去 score 属性并恢复，体现了 $\Sigma \leftrightarrow \Phi$ 的互逆本质。

---

## 4. 数据生成策略

### 4.1 未配对乐谱集 $\mathcal{D}_{\Sigma}$

使用启发式算法将乐谱切割成乐句（一般 4–8 measures），得到 $\sigma_{H_k}$ 和 $\sigma_{M_k}$。

生成的样本用于 **Score Language SFT**：
- phrase / measure continuation
- score mask reconstruction（$f$-mask）

### 4.2 未配对演奏集 $\mathcal{D}_{\Phi}$

使用 **Omnizart** 算法识别 downbeat，根据 downbeat 切割成小节 $\phi_{M_k}$，再通过启发式算法将多个小节连接成乐句 $\phi_{H_k}$。

生成的样本用于 **Performance Language SFT**：
- phrase / measure continuation
- performance mask reconstruction（$g$-mask）

> 如果 performance 的启发式 phrase 切分质量不佳，降级为 measure 级别使用。

### 4.3 小节级配对集 $\mathcal{D}_{\Sigma\Phi}^{M}$

先用启发式算法将乐谱切割成乐句（以 score 为主轴），再根据 measure 级配对信息将 performance 也切割成对应的乐句 $\phi_{H_k}$。

**配对质量控制**：如果 phrase 级对齐质量差（如 measure 数量不匹配、边界偏移过大），降级为未配对数据集使用，不用于 EPR / CSR。只有对齐可靠的配对才用于 EPR / CSR SFT。

生成的样本进入后续任务分支，不在 Step 1 使用：
- 完整 EPR rendering
- EPR attribute generation（$g$-mask）
- CSR head prediction
- Head-conditioned CSR
- CSR attribute recovery（$f$-mask）

其中 EPR 样本只进入 EPR Branch，CSR 样本只进入 CSR Branch。

### 4.4 通用规则

- **Performance 时间归一化**：目标小节内部的时间写成**相对 measure onset**，而非全曲绝对 tick，避免数字污染导致泛化差。
- **Phrase 内部结构**：对于长乐句（8 measures），可加 intra-phrase continuation 降低一次输出整个 phrase 的难度。
- **采样上限**：同一首曲子限制采样 K 个 windows（如 20–50 个），避免长曲子支配训练集。

---

## 5. 推荐训练流程与数据比例

### 5.1 Step 1：Language Learning SFT

Step 1 是共享底座，目标是让模型掌握 $\Sigma$ 与 $\Phi$ 两种文本语言，以及二者的格式规则。这个阶段的数据量可以比普通 SFT 更大，因为它承担的是 domain adaptation / 伪 CPT 的角色。

这个阶段只包含：

- Score Language
- Performance Language
- Knowledge QA
- format validation / repair
- score / performance mask reconstruction

不包含：

- EPR rendering
- CSR reconstruction
- EPR / CSR attribute generation / recovery

推荐比例：

| 任务类型 | 比例 | 说明 |
|---|---|---|
| Performance Language（continuation + $g$-mask） | 40–50% | 最终 EPR 输出是 performance，优先让模型熟悉 $\Phi$ |
| Score Language（continuation + $f$-mask） | 25–35% | 学习 $\Sigma$ 的谱面结构、声部、调性与小节关系 |
| Knowledge QA / validation / repair | 15–25% | 固化 ABCX、MIDI-TSV、mask、转换边界规则 |

保存 checkpoint：

```
spire-sft-language
```

### 5.2 Step 2a：EPR Branch SFT

从 `spire-sft-language` 初始化，只训练 EPR 相关任务。不要混入 CSR。

推荐比例：

| 任务类型 | 比例 | 说明 |
|---|---|---|
| Score-conditioned EPR（主任务） | 40–50% | 根据 score context + previous performance 生成当前 performance |
| Score-only EPR + Cold-start EPR | 20–25% | 无 performance context 时的渲染能力 |
| Intra-phrase EPR | 10–15% | 解决长乐句输出难度 |
| EPR attribute generation（$g$-mask） | 10–15% | 用 2.3 中定义的 $g$ mask 拆解表达属性，监督更干净 |
| Language / QA replay（可选） | 0–8% | 仅在格式遗忘时加入 |

如果 EPR 分支训练后 parse rate、measure continuity、event validity 没有下降，可以不加 Language replay；如果下降，优先 replay **Knowledge QA / repair**，其次才是 continuation。

保存 checkpoint：

```
spire-sft-epr
```

### 5.3 Step 2b：CSR Branch SFT

从 `spire-sft-language` 初始化，只训练 CSR 相关任务。不要混入 EPR。

推荐比例：

| 任务类型 | 比例 | 说明 |
|---|---|---|
| Head prediction（单乐句 + 投票） | 15–20% | 每个乐句独立预测 head |
| Head-conditioned CSR | 45–55% | CSR 主任务 |
| CSR attribute recovery（$f$-mask） | 20–30% | 用 2.3 中定义的 $f$ mask 补足 score 属性恢复能力 |
| Language / QA replay（可选） | 0–8% | 仅在格式遗忘时加入 |

保存 checkpoint：

```
spire-sft-csr
```

### 5.4 为什么不混成一个 SFT

EPR、CSR、Language 不应该作为同一个 SFT 的固定比例混合，原因：

| 问题 | 说明 |
|---|---|
| 目标方向相反 | EPR 是 $\Sigma \rightarrow \Phi$，CSR 是 $\Phi \rightarrow \Sigma$ |
| 输出语言不同 | EPR 主要输出 MIDI-TSV，CSR 主要输出 ABCX |
| 评价指标不同 | EPR 看 performance 对齐与表达性，CSR 看规范 score 恢复 |
| 数据质量门槛不同 | Language 可用未配对数据，EPR/CSR 需要高质量配对 |
| 分支用途不同 | 最终部署可能只需要 EPR 或只需要 CSR |

正确结构是：

```
Language Learning SFT
  ├── EPR Branch SFT
  └── CSR Branch SFT
```

而不是：

```
Single SFT = EPR + CSR + Language
```

### 5.5 最小可用版本（MVP）

如果只做 V1，分两步：

**Step 1: Language Learning**

1. $\sigma_{\text{head}} + \sigma_{H_k} \rightarrow \sigma_{H_{k+1}}$（Score continuation）
2. $g(\phi_{H_k}) \rightarrow \phi_{H_k}$（Performance language mask）
3. Knowledge QA / validation / repair

**Step 2a: EPR Branch**

1. $\sigma_{\text{head}} + \sigma_{H_{k-1}} + \sigma_{H_k} + \sigma_{H_{k+1}} \rightarrow \phi_{H_k}$（Score-only EPR）
2. $\sigma_{\text{head}} + \sigma_{H_{k-1}} + \sigma_{H_k} + \sigma_{H_{k+1}} + \phi_{H_{k-1}} \rightarrow \phi_{H_k}$（Score-conditioned EPR 主任务）
3. $\sigma_{\text{head}} + \sigma_{H_k} + g(\phi_{H_k}) \rightarrow \phi_{H_k}$（EPR attribute generation）

**Step 2b: CSR Branch** 可以后置；如果 V1 目标是 EPR，先不训练 CSR。

---

## 6. 训练经验与注意事项

1. **不要把 CPT 当成万能领域增强**——CPT 可能损伤通用指令能力
2. **分阶段理解数据质量与数量**——Step 1 Language Learning 可以大量使用合法、未污染数据；Step 2 EPR/CSR 分支更强调高质量配对与对齐
3. **结构化输出任务单独评估合法性**——不能只看 loss，要看 parse rate、duration conservation、measure boundary、event consistency
4. **LoRA / QLoRA 足够作为第一阶段实验**
5. **显式标记任务类型**——用 `<task>score_to_performance</task>` 等，不要把所有任务混在一个 prompt 模板里
6. **输出长度控制**——V1 最大 input 8 measures / output 8 measures，第二版再扩展到 16
7. **CSR head 投票**——单乐句独立预测 head 后按字段投票，不做大窗口联合预测

---

## 7. DPO / 偏好优化

### 7.1 阶段判断

```
EPR Branch SFT: 解决"能不能生成合法、对齐、完整的 performance"
EPR Branch DPO: 解决"哪个 render 更像人类偏好的演奏"
```

> 先 SFT，把 score-to-performance 和 attribute generation 做稳；再用 DPO 优化合法候选之间的表达性偏好。

### 7.2 DPO 触发条件

满足以下条件后再做 DPO：

- parse success rate > 95%
- note alignment error 较低
- measure boundary 基本正确
- score-conditioned rendering 已能生成完整 $\phi_{H_k}$
- 同一输入能采样出多个差异明显的候选
- 能定义 chosen / rejected 的偏好规则或人工标注标准

### 7.3 DPO 数据构造

| 方式 | chosen | rejected | 说明 |
|---|---|---|---|
| 自动劣化 | 真实 $\phi_{H_k}$ | 量化/平速度/去踏板/无 rubato 的 $\phi_{H_k}$ | 70%，易构造 |
| Reference vs Generated | 真实 $\phi_{H_k}$ | 模型生成的 $\phi_{H_k}$ | 20% |
| 人工标注 | 专家偏好 render | 较差 render | 10% |

> DPO 数据中 chosen 和 rejected 都必须是可解析的 MIDI-TSV。格式问题用 SFT/repair 解决；DPO 用于**合法候选之间的偏好排序**。V1 可从 5k–20k preference pairs 开始。

### 7.4 DPO 优化维度

| 维度 | 说明 |
|---|---|
| 合法性 | MIDI-TSV 可解析、event 顺序正确 |
| 对齐性 | note 与 score 对齐，不漏音、不多音 |
| 表达性 | velocity 有层次、timing 有自然 rubato |
| 踏板质量 | 不糊、不乱、不频繁异常切换 |
| 风格一致性 | 与前一乐句 $\phi_{H_{k-1}}$ 连续 |
| 乐句结构 | phrase ending 有收束，高潮处有推进 |

---

## 9. 实验设计与评估

### 9.1 实验目标

通过对比实验回答以下问题：
1. **Language Learning 是否必要？** 直接 EPR vs Language → EPR
2. **粒度如何选择？** Measure-level vs Phrase-level
3. **最优训练路径是什么？** 根据实验结果决定最终策略

### 9.2 模型状态定义

| 模型 | 训练路径 | 说明 |
|------|---------|------|
| **M0** | Qwen3.5-4B | 基础模型 |
| | | |
| **Measure-level 路径** | | |
| **M_M1** | M0 → Measure EPR | 直接学小节级 EPR（无 Language Learning） |
| **M_M2** | M0 → Measure Lang → Measure EPR | 先学小节级语言，再学 EPR |
| M_M3 | M0 → Measure Lang+QA → Measure EPR | 加入 QA/validation（V2） |
| | | |
| **Phrase-level 路径** | | |
| **M_H1** | M0 → Phrase EPR | 直接学乐句级 EPR（无 Language Learning） |
| **M_H2** | M0 → Phrase Lang → Phrase EPR | 先学乐句级语言，再学 EPR |
| M_H3 | M0 → Phrase Lang+QA → Phrase EPR | 加入 QA/validation（V2） |

**V1 优先级**：只训练 **M_M1, M_M2, M_H1, M_H2** 四个核心模型。

### 9.3 训练任务定义

#### Measure Lang（小节级语言学习）

```python
Measure_Lang = {
    # Score Language
    "score_measure_continuation": {
        "input": "σ_head + σ_{M_k}",
        "output": "σ_{M_{k+1}}",
        "weight": 0.25,
    },
    "score_measure_mask": {
        "input": "σ_head + f(σ_{M_k})",  # f ∈ {acc, treble, bass, label}
        "output": "σ_{M_k}",
        "weight": 0.25,
    },
    
    # Performance Language
    "perf_measure_continuation": {
        "input": "φ_{M_k}",
        "output": "φ_{M_{k+1}}",
        "weight": 0.25,
    },
    "perf_measure_mask": {
        "input": "g(φ_{M_k})",  # g ∈ {timing, velocity, duration, pedal}
        "output": "φ_{M_k}",
        "weight": 0.25,
    },
}
```

#### Phrase Lang（乐句级语言学习）

```python
Phrase_Lang = {
    # Score Language
    "score_phrase_continuation": {
        "input": "σ_head + σ_{H_k}",
        "output": "σ_{H_{k+1}}",
        "weight": 0.25,
    },
    "score_phrase_mask": {
        "input": "σ_head + f(σ_{H_k})",
        "output": "σ_{H_k}",
        "weight": 0.25,
    },
    
    # Performance Language
    "perf_phrase_continuation": {
        "input": "φ_{H_k}",
        "output": "φ_{H_{k+1}}",
        "weight": 0.25,
    },
    "perf_phrase_mask": {
        "input": "g(φ_{H_k})",
        "output": "φ_{H_k}",
        "weight": 0.25,
    },
}
```

#### Measure EPR（小节级演奏渲染）

```python
Measure_EPR = {
    "measure_epr_main": {
        "input": "σ_head + σ_{M_{k-1}} + σ_{M_k} + σ_{M_{k+1}}",
        "output": "φ_{M_k}",
        "weight": 0.8,
    },
    "measure_epr_coldstart": {
        "input": "σ_head + σ_{M_1} + σ_{M_2}",
        "output": "φ_{M_1}",
        "weight": 0.2,
    },
}
```

#### Phrase EPR（乐句级演奏渲染）

```python
Phrase_EPR = {
    "phrase_epr_main": {
        "input": "σ_head + σ_{H_{k-1}} + σ_{H_k} + σ_{H_{k+1}}",
        "output": "φ_{H_k}",
        "weight": 0.8,
    },
    "phrase_epr_coldstart": {
        "input": "σ_head + σ_{H_1} + σ_{H_2}",
        "output": "φ_{H_1}",
        "weight": 0.2,
    },
}
```

### 9.4 V1 实验方案

**训练模型**（4个）：
1. **M_M1**: M0 → Measure EPR（直接）
2. **M_M2**: M0 → Measure Lang → Measure EPR
3. **M_H1**: M0 → Phrase EPR（直接）
4. **M_H2**: M0 → Phrase Lang → Phrase EPR

**对比维度**：
- **M_M1 vs M_M2**：Measure-level 的 Language Learning 作用
- **M_H1 vs M_H2**：Phrase-level 的 Language Learning 作用
- **M_M1 vs M_H1**：粒度对直接 EPR 的影响
- **M_M2 vs M_H2**：粒度对完整路径的影响

**数据来源**：
- 使用相同的 PianoCoRe 配对数据集
- Measure-level：切分成小节级样本
- Phrase-level：切分成乐句级样本（4-8 小节）
- 数据量由数据集本身决定，不人为控制 token 数

**训练配置**：
- Base model: Qwen3.5-4B
- Method: LoRA (r=64, alpha=128)
- Learning rate: 2e-5
- Epochs: 3

**决策逻辑**：
- 如果 M_M2 >> M_M1 且 M_H2 >> M_H1 → Language Learning 有效
- 如果 M_M1 ≈ M_M2 且 M_H1 ≈ M_H2 → Language Learning 无效，直接 EPR
- 如果 Measure >> Phrase → 选择 Measure-level
- 如果 Phrase >> Measure → 选择 Phrase-level

---

## 10. 术语定义

| 缩写 | 全称 | 含义 | 公式 |
|---|---|---|---|
| **EPR** | Expressive Performance Rendering | 从 score 生成 expressive performance | $\Sigma \rightarrow \Phi$ |
| **CSR** | Canonical Score Reconstruction | 从 performance 恢复规范 score | $\Phi \rightarrow \Sigma$ |
| **PM2S** | Performance MIDI-to-Score Conversion | 已有 MIR 术语（Liu et al. ISMIR 2022），与 CSR 类似但偏工程命名 | — |
| **M_M1** | Measure Model 1 | 直接 Measure EPR（无 Language Learning） | M0 → Measure EPR |
| **M_M2** | Measure Model 2 | Measure Lang → Measure EPR | M0 → Measure Lang → Measure EPR |
| **M_H1** | pHrase Model 1 | 直接 Phrase EPR（无 Language Learning） | M0 → Phrase EPR |
| **M_H2** | pHrase Model 2 | Phrase Lang → Phrase EPR | M0 → Phrase Lang → Phrase EPR |

> CSR 与 EPR 对称，强调从带有演奏偏差的 performance 中恢复规范化、可记谱的 score 表示。PM2S 是已有文献术语但影响力有限（~20 次引用），可在 related work 中提及，不作为主任务名。
> 
> 模型命名：M = Measure, H = pHrase（避免与 MIDI-TSV 中的 H=phrase header 混淆），数字表示训练路径（1=直接EPR，2=Lang→EPR）。



还有一个步骤能不能顺便做了，形成一个完整的挖掘算法，就是：

假设所有score mxl/xml 都已经生成了对应的abcx
Step 1: 从 Score MIDI 定义"逻辑小节"，输出一个json
Step 2: 使用启发式算法识别原始 abcx 的乐句。并根据score midi json对齐相应的abcx，现在abcx body的结构如下：

H1\t|:M1|M2|$M3|M4:|$
M1\t!p!"^Allegro ma con tenerezza" ([ce]4 ; z4 ; "^con pedale" z A,A,A,
M2\t!<(! [df]4 ; z4 ; z A,A,A,
M3\t[B^g]4!<)! ; z4 ; z A,A,A,
M4\t[ca]4) ; z4 ; !f! z (A,E,C,
H2\tM5|M6|$M7|...
M5\t(c'e){/g}(fe) ; z4 ; A,,4)
M6\t(e2 ^d) z ; z4 ; z (B,,B,A,
M7\t(b=d){/f}(ed) ; z4 ; ^G,4)

就是去掉小节号，每个小节的内容对齐一个score midi小节，如果有多余的音符或者小节则去掉
除此之外，添加启发式乐句结构，包括标题 + 乐句结构，要求abcx通过乐句还原的方式能够复现原始的abcx，乐句结构使用 MX表示相应的小节内容，使用 $ 表示换行
然后我们将乐句结构（每个小节分别在什么乐句里）也写入json中

Step 3: Performance 根据json和相应的npz对齐，自动检测repeat，并使用相同的小节。注意根据小节分配乐句，即如果当前小节所在乐句与前一小节不同，或者当前小节是乐句的第一个小节，则添加乐句符号。

这样performance midi 既有小节也有乐句。同时 performance 可以与 score 完全对齐



PianoCoRe_aligned/Arndt,_Felix/Desecration

这首曲子有点问题：tsv 与 abcx_aligned 不对齐
tsv 中 M1 是 FGA,C
而 abcx 中 M1 不存在，从M2开始，而M2都是休止符，所以真正M3 才对应 tsv的M1