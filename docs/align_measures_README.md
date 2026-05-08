# 小节配对算法

## 概述

`align_measures.py` 实现了ABCX乐谱小节与MIDI演奏的自动对齐。算法基于F1分数（Precision和Recall的调和平均）评估匹配质量。

## 快速开始

```bash
python3 align_measures.py <abcx_file> <midi_file>
```

示例：
```bash
python3 align_measures.py \
    data/abc_from_xml/Glinka/The_Lark/Glinka_The_Lark.abcx \
    data/asap-dataset/Glinka/The_Lark/Denisova10M.mid
```

输出：
```
1:16
2:64
3:84
4:144
```

## 算法原理

### 评估指标（基于论文）

- **Recall（召回率）**：小节中有多少音符在窗口中出现
- **Precision（精确度）**：窗口中有多少音符是小节需要的
- **F1 Score**：`2 * Precision * Recall / (Precision + Recall)`

### 工作流程

1. 解析ABCX文件，提取每个小节的音符
2. 将MIDI转换为TSV格式
3. 使用滑动窗口搜索最佳匹配位置
4. 基于F1分数选择最优对齐

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--threshold` | 0.3 | F1分数阈值 |
| `--min-gap` | 15 | 相邻小节最小间隔（行数） |
| `--search-range` | 200 | 搜索范围（事件数） |
| `-v, --verbose` | - | 显示详细信息 |
| `-o, --output` | - | 保存结果到文件 |

## 当前状态

### 已实现
✓ 基于F1分数的匹配评估  
✓ 多窗口大小搜索（30-60行）  
✓ 时间约束（最小间隔）  
✓ 行号范围窗口（而非事件索引）

### 测试结果
在Glinka《云雀》上的测试：
- 小节1、2、4：正确匹配
- 其他小节：部分偏差

### 已知限制
1. 贪心策略导致错误累积
2. 固定窗口大小不适应所有情况
3. 缺少全局优化

## 改进方向

1. **动态规划**：全局最优对齐
2. **时间信息**：利用MIDI tick估算小节时长
3. **DTW算法**：处理速度变化
4. **多阶段对齐**：粗定位 + 精匹配
5. **集成现有工具**：如Nakamura对齐算法

## 依赖

- Python 3.6+
- `wave-roll-studio/midi_tsv.py`
