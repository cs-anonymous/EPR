# EPR 论文提纲：基于语言模型的富表达钢琴演奏渲染

## 论文标题（候选）

1. **InSPIRE: Instruction-tuned Score–Performance Interpretation and Rendering for Musical Expression**
2. **ABCX-to-Performance: A Language Model Approach for Expressive Piano Rendering**
3. **Beyond Score MIDI: Expressive Piano Performance Rendering with Symbolic Music Understanding**

---

## Abstract（摘要结构）

**背景**：钢琴演奏表达建模（Expressive Performance Rendering, EPR）旨在将乐谱转换为富含表达的演奏。现有方法主要使用回归模型，输入为 Score MIDI，输出为演奏偏差参数。

**问题**：
1. Score MIDI 信息量有限，缺少谱面标记（强弱术语、连音线、踏板标记等）
2. 传统回归方法难以建模一对多的演奏多样性
3. 缺少反向任务（Performance → Score）导致数据获取成本高

**方法**：提出双向符号-表演翻译框架：
- 使用 ABCX（高信息量符号表示）替代 Score MIDI
- 采用 LLM 进行 next-token prediction，天然支持多样性采样
- 同时训练正向（ABCX → MIDI-TSV）和反向（MIDI-TSV → ABCX）任务

**贡献**：
1. 首个基于 LLM 的双向 EPR 系统
2. 构建了包含 ABCX-Score MIDI-Performance MIDI 三元组的对齐数据集
3. 反向任务实现数据飞轮，降低数据标注成本
4. 在 ASAP/MAESTRO 上的实验表明优于传统回归方法

**结果**：在 timing RMSE、velocity correlation、人类盲听测试等指标上达到 SOTA 或接近水平。

---

## 1. Introduction

### 1.1 研究背景与动机
