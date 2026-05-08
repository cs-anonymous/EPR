# Measure-Level Alignment: 结论与建议

## 实验结果总结

### 1. ASAP Annotations方法 ⭐⭐⭐
**文件**: `align_from_asap_annotations.py`

**准确率**:
- 精确匹配: 71.1% (54/76)
- ±5 tolerance: 98.7% (75/76)

**优点**:
- 使用ASAP数据集提供的高质量beat-level annotations
- 准确率高，几乎完美
- 实现简单，直接读取downbeat时间

**限制**:
- 只适用于ASAP数据集
- 需要预先存在的annotations文件

**使用场景**: ASAP数据集的measure-level对齐

---

### 2. 自实现算法（DP + 局部打分）
**文件**: `align_measures_final.py`

**准确率**:
- 精确匹配: 11.8%
- ±100 tolerance: 61.8%

**优点**:
- 使用绝对pitch（而非pitch class）
- 考虑音符时长
- 完全独立，不依赖外部工具

**问题**:
- 贪心搜索导致误差累积
- 当一个小节匹配错误时，影响后续所有小节
- 准确率远低于ASAP annotations

**使用场景**: 作为baseline参考

---

### 3. Note-level DTW方法
**文件**: `align_with_note_dtw.py`

**准确率**:
- 精确匹配: 1.8%
- 与原始算法相同，几乎完全失败

**问题**:
1. **多个小节可能有相同的第一个音符**
   - 例如：小节1和小节2都以pitch 65开始
   - 贪心匹配会选择错误的occurrence

2. **没有强制时间顺序约束**
   - DTW路径本身是单调的
   - 但在映射measure-start notes时，没有保证顺序
   - 导致小节3映射到tick 29932，小节4映射到tick 1671（乱序）

3. **DTW特征选择问题**
   - 使用[pitch, log_duration, pitch_class]特征
   - 但performance和score之间的duration差异很大
   - 导致DTW路径不准确

**根本原因**: 
- Note-level alignment是一个复杂的研究问题
- 需要处理tempo变化、装饰音、省略音、重复等
- 简单的DTW + 贪心匹配无法处理这些情况

---

## 核心问题分析

### 为什么自己实现的算法效果不好？

1. **Note-level alignment是成熟的研究领域**
   - 已有大量论文和成熟工具（Partitura, madmom, music21）
   - 需要复杂的特征工程和对齐算法
   - 不应该重新造轮子

2. **从note-level粗化到measure-level不是简单的映射**
   - 需要准确识别每个小节的第一个音符
   - 需要处理ABCX和MIDI之间的对应关系
   - 需要处理performance中的变化（tempo、dynamics、articulation）

3. **贪心匹配的根本缺陷**
   - 当多个小节有相同的第一个音符时，无法区分
   - 没有全局优化，局部错误会累积
   - 需要更复杂的约束和搜索策略

---

## 推荐方案

### 对于ASAP数据集

**直接使用annotations** (`align_from_asap_annotations.py`)

```bash
python3 align_from_asap_annotations.py \
    data/asap-dataset/Glinka/The_Lark/midi_score_annotations.txt \
    data/asap-dataset/Glinka/The_Lark/Denisova10M_annotations.txt
```

**准确率**: 71.1%（精确），98.7%（±5）

---

### 对于任意score和performance MIDI

**使用成熟的alignment工具**：

#### 选项1: Partitura
```bash
pip install partitura
```

**问题**: Partitura没有内置的note-level alignment功能
- `load_match`只能加载已有的match文件
- 没有`match.match_note_alignments`函数
- 需要自己实现alignment算法

#### 选项2: madmom
```bash
pip install madmom
```

**特点**:
- 专注于音乐信息检索
- 提供beat tracking和onset detection
- 可以用于实现类似ASAP的beat-level alignment

#### 选项3: 使用ASAP的方法论
- ASAP使用Hierarchical DTW + symbolic note matching
- 可以研究其实现并应用到任意MIDI对
- 需要实现beat tracking和note alignment

---

## 建议的Pipeline（通用方案）

```
1. 使用成熟工具进行beat tracking
   - madmom的beat tracking
   - 或实现ASAP的Hierarchical DTW
   ↓
2. 从ABCX提取每个小节的第一个音符
   ↓
3. 在score MIDI中找到对应的音符及其beat位置
   ↓
4. 通过beat-level alignment映射到performance MIDI
   ↓
5. 输出measure-level对齐结果
```

---

## 经验教训

1. **不要重新造轮子**
   - Note-level alignment是成熟的研究领域
   - 使用现有工具可以节省大量时间
   - 专注于自己的核心问题（measure-level粗化）

2. **理解问题的复杂性**
   - Performance和score之间的差异很大
   - 需要鲁棒的特征和算法
   - 简单的方法很难达到高准确率

3. **利用现有资源**
   - ASAP数据集提供了高质量的annotations
   - 可以作为训练数据或评估基准
   - 可以学习其方法论

4. **贪心匹配的局限性**
   - 当有重复元素时，贪心匹配会失败
   - 需要全局优化或更强的约束
   - 时间顺序约束必须在匹配过程中强制执行

---

## 下一步建议

### 短期（使用现有工具）

1. **对于ASAP数据集**: 直接使用`align_from_asap_annotations.py`

2. **对于任意MIDI对**: 
   - 安装madmom: `pip install madmom`
   - 实现beat tracking
   - 将beat-level对齐粗化到measure-level

### 长期（深度学习方法）

1. **训练note-level alignment模型**
   - 使用ASAP数据集作为训练数据
   - 使用Transformer或RNN进行序列对齐
   - 可以达到更高的准确率

2. **端到端的measure-level alignment**
   - 直接从MIDI和ABCX预测measure boundaries
   - 避免两阶段pipeline的误差累积

---

## 参考资源

1. **ASAP Dataset**
   - Paper: "ASAP: A Dataset of Aligned Scores and Performances for Piano Music"
   - GitHub: https://github.com/fosfrancesco/asap-dataset

2. **madmom**
   - GitHub: https://github.com/CPJKU/madmom
   - Paper: "madmom: a new Python Audio and Music Signal Processing Library"

3. **相关论文**
   - "Online Time Warping for Real-Time Audio-to-Score Alignment"
   - "A Multi-Model Approach to Beat Tracking Considering Heterogeneous Music Styles"
   - "Learning to Align: A Statistical Approach"

---

## 代码文件说明

### 推荐使用

1. **align_from_asap_annotations.py** ⭐⭐⭐
   - 准确率: 71.1%（精确），98.7%（±5）
   - 只适用于ASAP数据集

### 可作为参考

2. **align_measures_final.py**
   - 准确率: 11.8%（精确），61.8%（±100）
   - 可作为baseline

### 不推荐使用

3. **align_with_note_dtw.py**
   - 准确率: 1.8%（几乎完全失败）
   - 贪心匹配导致乱序

4. **align_with_dtw.py**
   - 使用chroma特征的DTW
   - 所有小节映射到同一位置

5. **align_simple_greedy.py**
   - 简单贪心匹配
   - 没有顺序约束，结果混乱

6. **align_measures_global_dp.py**
   - 全局DP
   - 路径断裂，无法找到有效路径
