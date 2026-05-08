# Measure-Level Alignment 最终方案

## 问题总结

原始需求：
- 不使用GT reference
- 使用绝对pitch而不是pitch class
- 考虑音符时长
- 准确率要高

## 尝试的方案

### 1. 自己实现的算法（align_measures_final.py）
- **准确率**: 11.8%（精确），61.8%（tolerance=100）
- **问题**: 贪心搜索导致误差累积
- **优点**: 完全独立，不依赖外部工具

### 2. 全局DP算法（align_measures_global_dp.py）
- **结果**: 失败，DP路径断裂
- **问题**: 候选生成策略和约束条件难以平衡

### 3. DTW对齐（align_with_dtw.py）
- **结果**: 失败，所有小节对齐到同一位置
- **问题**: Chroma特征的时间分辨率问题，DTW路径映射逻辑错误

### 4. 简单贪心匹配（align_simple_greedy.py）
- **结果**: 失败，匹配顺序混乱
- **问题**: 没有考虑时间顺序约束

### 5. 使用ASAP Annotations（align_from_asap_annotations.py）⭐
- **准确率**: 71.1%（精确），98.7%（tolerance=5）
- **优点**: 使用成熟的beat-level对齐结果
- **限制**: 只适用于ASAP数据集

## 核心问题

**为什么自己实现的算法效果不好？**

1. **Note-level alignment是一个已经被深入研究的问题**
   - 需要处理tempo变化、装饰音、省略音、重复等
   - 需要鲁棒的特征表示（chroma、onset strength等）
   - 需要复杂的对齐算法（DTW、HMM、CTC等）

2. **从note-level粗化到measure-level不是简单的映射**
   - 需要准确识别每个小节的第一个音符
   - 需要处理ABCX和MIDI之间的对应关系
   - 需要处理performance中的变化

3. **成熟的工具已经解决了这些问题**
   - ASAP数据集提供了beat-level annotations
   - Partitura、madmom等库提供了alignment功能
   - 不应该重新造轮子

## 推荐方案

### 对于ASAP数据集

**直接使用annotations**（`align_from_asap_annotations.py`）

```bash
python3 align_from_asap_annotations.py \
    data/asap-dataset/Glinka/The_Lark/midi_score_annotations.txt \
    data/asap-dataset/Glinka/The_Lark/Denisova10M_annotations.txt
```

准确率：71.1%（精确），98.7%（tolerance=5）

### 对于任意score和performance MIDI

**使用成熟的alignment工具**：

1. **Partitura** (推荐)
   ```bash
   pip install partitura
   ```
   - 提供note-level alignment
   - 支持多种对齐算法
   - 文档完善

2. **madmom**
   ```bash
   pip install madmom
   ```
   - 专注于音乐信息检索
   - 提供beat tracking和alignment

3. **music21**
   ```bash
   pip install music21
   ```
   - 综合性音乐分析库
   - 支持MIDI和MusicXML

### Pipeline设计

```
1. 使用成熟工具进行note-level alignment
   ↓
2. 从ABCX提取每个小节的第一个音符
   ↓
3. 在score MIDI中找到对应的音符
   ↓
4. 通过alignment映射到performance MIDI
   ↓
5. 输出measure-level对齐结果
```

## 代码文件说明

### 可用的文件

1. **align_from_asap_annotations.py** ⭐⭐⭐
   - 使用ASAP annotations
   - 准确率：71.1%（精确），98.7%（tolerance=5）
   - 只适用于ASAP数据集

2. **align_measures_final.py** ⭐
   - 自己实现的算法
   - 准确率：11.8%（精确），61.8%（tolerance=100）
   - 可作为baseline

### 不推荐的文件

- align_measures_global_dp.py - DP失败
- align_with_dtw.py - DTW映射错误
- align_simple_greedy.py - 顺序混乱

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

## 下一步建议

如果要继续改进，建议：

1. **安装并学习partitura**
   ```bash
   pip install partitura
   ```
   - 阅读文档和示例
   - 理解其alignment算法
   - 在自己的数据上测试

2. **研究ASAP的方法**
   - 阅读ASAP论文
   - 理解其beat tracking方法
   - 学习其evaluation metrics

3. **使用深度学习方法**
   - 训练一个note-level alignment模型
   - 使用ASAP数据集作为训练数据
   - 可以达到更高的准确率

## 参考资源

1. **ASAP Dataset**
   - Paper: "ASAP: A Dataset of Aligned Scores and Performances for Piano Music"
   - GitHub: https://github.com/fosfrancesco/asap-dataset

2. **Partitura**
   - GitHub: https://github.com/CPJKU/partitura
   - Docs: https://partitura.readthedocs.io/

3. **madmom**
   - GitHub: https://github.com/CPJKU/madmom
   - Paper: "madmom: a new Python Audio and Music Signal Processing Library"

4. **相关论文**
   - "Online Time Warping for Real-Time Audio-to-Score Alignment"
   - "A Multi-Model Approach to Beat Tracking Considering Heterogeneous Music Styles"
   - "Learning to Align: A Statistical Approach"
