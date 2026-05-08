# 小节对齐算法最终总结

## 问题回顾

原算法的核心问题：
1. ❌ 使用pitch class（0-11）而不是绝对pitch
2. ❌ 完全忽略音符时长
3. ❌ Without GT Reference准确率只有1.8%
4. ❌ GT reference被错误地用在算法中

## 改进尝试

### 方案1：align_measures_final.py（当前最佳）

**改进：**
- ✅ 使用绝对pitch（MIDI note number）
- ✅ 提取音符时长信息
- ✅ 完全不使用GT reference
- ✅ 改进位置估计（基于音符数量加权）
- ✅ 更宽的搜索范围（+/- 50%）

**结果：**
- 精确匹配：11.8%（从1.8%提升6.5倍）
- Tolerance=100: 61.8%

**问题：**
- 贪心搜索导致误差累积
- 一个小节错误会影响后续小节

### 方案2：align_measures_global_dp.py（失败）

**设计：**
- 全局动态规划（类似DTW）
- 为每个小节在整个MIDI中生成候选
- 使用DP找全局最优路径

**问题：**
- DP路径断裂（在小节8失败）
- 候选生成策略有问题
- 约束条件难以平衡

## 根本原因分析

### 为什么全局DP失败？

1. **候选位置稀疏**：
   - 只在第一个音符匹配的位置生成候选
   - 如果第一个音符在performance中被省略或延迟，就找不到候选
   - 平均每个小节只有15.7个候选，可能不够

2. **单调性约束太强**：
   - 要求`ev2 > ev1`（严格递增）
   - 但performance中可能有重复、回退等情况
   - 导致DP路径断裂

3. **局部打分器不够鲁棒**：
   - 依赖第一个音符匹配
   - 对performance的变化（装饰音、省略音等）不够容忍

## 推荐方案

基于当前的实验结果，我建议：

### 短期方案：使用align_measures_final.py

虽然准确率只有11.8%，但它是目前唯一能稳定工作的版本。

**优点：**
- 稳定运行，不会失败
- 比原算法提升6.5倍
- 在tolerance=100时达到61.8%

**使用场景：**
- 作为baseline
- 用于初步对齐，然后人工校正
- 对准确率要求不高的场景

### 长期方案：借鉴成熟的music synchronization方法

建议参考以下论文和工具：

1. **Dynamic Time Warping (DTW)**：
   - 经典的序列对齐算法
   - 对tempo变化有很好的容忍度
   - 可以处理局部的插入、删除、替换

2. **Online Time Warping (OTW)**：
   - DTW的在线版本
   - 适合实时对齐

3. **Hidden Markov Model (HMM)**：
   - 概率模型，更鲁棒
   - 可以建模performance的不确定性

4. **现有工具**：
   - **librosa**: Python音频分析库，有DTW实现
   - **madmom**: 音乐信息检索库，有beat tracking和alignment功能
   - **pretty_midi**: MIDI处理库
   - **music21**: 音乐分析库

### 具体改进建议

如果要继续改进当前算法，建议：

1. **改进候选生成**：
   - 不只依赖第一个音符
   - 使用滑动窗口，在每个位置都评分
   - 保留更多候选（top-50而不是top-20）

2. **改进局部打分器**：
   - 使用chroma特征而不是绝对pitch（对八度错误更容忍）
   - 加入duration相似度
   - 使用更复杂的序列匹配算法（如Smith-Waterman）

3. **放宽DP约束**：
   - 允许小幅回退（处理performance中的重复）
   - 使用软约束而不是硬约束
   - 动态调整约束强度

4. **多次迭代**：
   - 第一次粗对齐
   - 使用粗对齐结果改进位置估计
   - 第二次精细对齐

5. **使用duration信息**：
   - 计算每个小节的总duration
   - 在MIDI中查找duration相似的片段
   - 结合pitch和duration进行匹配

## 代码文件说明

### 可用的文件

1. **align_measures_final.py** ⭐ 推荐使用
   - 当前最佳方案
   - 准确率：11.8%（精确），61.8%（tolerance=100）
   - 稳定可靠

2. **evaluate_alignment_v2.py**
   - 评估脚本
   - 支持不同tolerance

3. **quick_eval.py**
   - 快速评估脚本
   - 显示不同tolerance下的准确率

### 不推荐使用的文件

1. **align_measures_v2.py** - 准确率5.26%，比final差
2. **align_measures_v3.py** - 准确率2.6%，更差
3. **align_measures_v4.py** - 运行太慢，未完成
4. **align_measures_global_dp.py** - DP失败，无输出

## 使用示例

```bash
# 运行对齐算法
python3 align_measures_final.py \
    data/abc_from_xml/Glinka/The_Lark/Glinka_The_Lark.abcx \
    data/asap-dataset/Glinka/The_Lark/Denisova10M.mid \
    --verbose

# 评估准确率
python3 quick_eval.py

# 输出：
# Tolerance   0:  11.8% (9/76)
# Tolerance   1:  15.8% (12/76)
# Tolerance   5:  22.4% (17/76)
# Tolerance  10:  26.3% (20/76)
# Tolerance  50:  40.8% (31/76)
# Tolerance 100:  61.8% (47/76)
```

## 结论

1. **成功之处**：
   - 证明了使用绝对pitch的可行性
   - 证明了不依赖GT reference的可行性
   - 准确率提升了6.5倍

2. **仍需改进**：
   - 11.8%的准确率对实际应用来说还不够
   - 需要更复杂的算法（DTW、HMM等）
   - 需要充分利用duration信息

3. **建议**：
   - 短期：使用align_measures_final.py作为baseline
   - 长期：参考成熟的music synchronization方法
   - 考虑使用现有工具（librosa、madmom等）
