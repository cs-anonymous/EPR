# SPIRE SFT 设计

## 1. 核心问题：CPT 还是 SFT？

### 1.1 判断标准

- **目标决定方法**：如果目标是论文任务效果（score→performance、format conversion），SFT 优先；如果目标是训练一个音乐文本基础模型（通用补全、续写、风格迁移），CPT 更必要。
- **SFT 可替代 CPT 的三种情况**：
  1. 基础模型已有较强的代码/表格/结构化文本能力（MIDI-TSV、ABCX 本质是结构化文本）
  2. 目标任务明确（score→performance、format conversion、repair）
  3. 能构造大量高质量任务样本
- **SFT 不能替代 CPT 的情况**：模型完全不熟悉表示语言；大量无标注数据但配对数据少；需要通用领域补全能力；SFT 数据覆盖不足。

### 1.2 两步 + 分支路线

```
Base LLM
  → Step 1：SPIRE Language Learning SFT
      - Score Language
      - Performance Language
      - Knowledge QA / validation / repair
      保存：spire-sft-language

  → Step 2a：EPR Branch SFT
      - score → expressive performance
      保存：spire-sft-epr

  → Step 2b：CSR Branch SFT
      - performance → canonical score
      保存：spire-sft-csr
```

> 第一版不做正式 CPT，先用 **Language Learning SFT** 替代 CPT。等发现格式分布不稳、长序列结构断裂时，再补小规模 CPT 作为 ablation。

关键原则：

1. **Step 1 只学习语言和规则**：包括 Score Language、Performance Language、Knowledge QA、format validation、repair、mask reconstruction；不训练 EPR / CSR 主任务。
2. **Step 2 才进入任务分支**：从同一个 `spire-sft-language` checkpoint 分叉，分别训练 EPR 和 CSR。
3. **不要做一个混合 EPR/CSR/Language 的大 SFT**：EPR 与 CSR 方向相反，目标分布不同，混在一个阶段容易互相稀释。
4. **Language replay 是分支阶段的可选正则项**：如果 EPR/CSR 分支出现格式遗忘，加入少量 Language / QA replay；如果格式稳定，可以不加。

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

### 3.1 Score Language

学习乐谱表示的语法、结构、乐句延续。

| 任务 | 公式 | 优先级 | 说明 |
|---|---|---|---|
| Phrase continuation | $\sigma_{\text{head}} + \sigma_{H_k} \rightarrow \sigma_{H_{k+1}}$ | 中 | 学乐谱乐句延续、重复与变奏 |
| Measure continuation | $\sigma_{\text{head}} + \sigma_{M_k} \rightarrow \sigma_{M_{k+1}}$ | 低 | 学局部格式、measure boundary |
| Measure mask reconstruction | $\sigma_{\text{head}} + f(\sigma_{M_k}) \rightarrow \sigma_{M_k}$ | 中 | 用 $f$ 遮去部分信息后恢复 |

> $f$ 的具体变体见 [2.3 Mask 函数定义](#23-mask-函数定义)，包括 acc / treble / bass / label 等。

### 3.2 Performance Language

学习 performance MIDI 的事件分布、属性连续性。

| 任务 | 公式 | 优先级 | 说明 |
|---|---|---|---|
| Phrase continuation | $\phi_{H_k} \rightarrow \phi_{H_{k+1}}$ | 低-中 | 学 performance 分布（辅助任务） |
| Measure continuation | $\phi_{M_k} \rightarrow \phi_{M_{k+1}}$ | 中 | 学局部演奏事件分布 |
| Phrase mask reconstruction | $g(\phi_{H_k}) \rightarrow \phi_{H_k}$ | 高 | 用 $g$ 遮去某一类属性后恢复 |

> $g$ 的具体变体见 [2.3 Mask 函数定义](#23-mask-函数定义)，包括 timing / velocity / duration / pedal 等。

### 3.3 EPR：Expressive Performance Rendering

从 score 生成 expressive performance。分为完整渲染与属性生成两类。

#### 完整渲染

| 任务 | 公式 | 优先级 | 说明 |
|---|---|---|---|
| **Score-conditioned EPR（主任务）** | $\sigma_{\text{head}} + \sigma_{H_{k-1}} + \sigma_{H_k} + \sigma_{H_{k+1}} + \phi_{H_{k-1}} \rightarrow \phi_{H_k}$ | **最高** | 根据前后乐句 + 前句演奏风格生成当前演奏 |
| Score-only EPR | $\sigma_{\text{head}} + \sigma_{H_{k-1}} + \sigma_{H_k} + \sigma_{H_{k+1}} \rightarrow \phi_{H_k}$ | 高 | 无 performance context 时渲染任意乐句 |
| Cold-start EPR | $\sigma_{\text{head}} + \sigma_{H_1} + \sigma_{H_2} \rightarrow \phi_{H_1}$ | 高 | 曲子开头渲染（无前文） |
| Intra-phrase EPR | $\sigma_{\text{head}} + \sigma_{H_k} + \text{partial } \phi_{H_k} \rightarrow \text{remaining } \phi_{H_k}$ | 高 | 长乐句内部续写 |
| EPR attribute generation | $\sigma_{\text{head}} + \sigma_{H_k} + g(\phi_{H_k}) \rightarrow \phi_{H_k}$ | 中 | 用 2.3 中定义的 $g$ mask 生成 timing / velocity / duration / pedal 等演奏属性 |

> Priority: **timing > velocity > duration > pedal**。pitch mask 不推荐——pitch 大多由 score 决定，不是 expressive performance 的主要难点。

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

## 8. 术语定义

| 缩写 | 全称 | 含义 | 公式 |
|---|---|---|---|
| **EPR** | Expressive Performance Rendering | 从 score phrase 生成 expressive performance phrase | $\Sigma \rightarrow \Phi$ |
| **CSR** | Canonical Score Reconstruction | 从 performance phrase 恢复规范 score phrase | $\Phi \rightarrow \Sigma$ |
| **PM2S** | Performance MIDI-to-Score Conversion | 已有 MIR 术语（Liu et al. ISMIR 2022），与 CSR 类似但偏工程命名 | — |

> CSR 与 EPR 对称，强调从带有演奏偏差的 performance 中恢复规范化、可记谱的 score 表示。PM2S 是已有文献术语但影响力有限（~20 次引用），可在 related work 中提及，不作为主任务名。
