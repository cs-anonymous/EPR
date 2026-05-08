# 小节配对算法使用说明

## 功能描述

`align_measures.py` 是一个用于将 ABCX 文件中的小节与 MIDI-TSV 文件中的行数对应起来的工具。

该算法通过匹配每个小节的第一个音符，找到其在 MIDI-TSV 文件中对应的位置（行号）。

## 使用方法

### 基本用法

```bash
python3 align_measures.py <abcx_file> <midi_file>
```

**示例：**
```bash
python3 align_measures.py \
    data/abc_from_xml/Glinka/The_Lark/Glinka_The_Lark.abcx \
    data/asap-dataset/Glinka/The_Lark/Denisova10M.mid
```

**输出：**
```
1:16 2:64 3:82 4:84 5:145 6:164 ...
```

格式说明：`小节号:TSV行号`

### 详细输出模式

使用 `-v` 或 `--verbose` 参数显示处理过程：

```bash
python3 align_measures.py -v \
    data/abc_from_xml/Glinka/The_Lark/Glinka_The_Lark.abcx \
    data/asap-dataset/Glinka/The_Lark/Denisova10M.mid
```

**输出：**
```
解析 ABCX 文件: data/abc_from_xml/Glinka/The_Lark/Glinka_The_Lark.abcx
找到 76 个小节
转换 MIDI 文件: data/asap-dataset/Glinka/The_Lark/Denisova10M.mid
解析 TSV 文件: /tmp/tmpXXXXXX.tsv
找到 1324 个音符事件
查找小节对齐...

结果 (76/76 个小节已对齐):
1:16 2:64 3:82 4:84 ...
```

### 保存结果到文件

使用 `-o` 或 `--output` 参数：

```bash
python3 align_measures.py \
    data/abc_from_xml/Glinka/The_Lark/Glinka_The_Lark.abcx \
    data/asap-dataset/Glinka/The_Lark/Denisova10M.mid \
    -o alignment_result.txt
```

### 保留 TSV 文件

默认情况下，临时生成的 TSV 文件会被自动删除。使用 `--keep-tsv` 参数保留：

```bash
python3 align_measures.py --keep-tsv -v \
    data/abc_from_xml/Glinka/The_Lark/Glinka_The_Lark.abcx \
    data/asap-dataset/Glinka/The_Lark/Denisova10M.mid
```

## 参数说明

| 参数 | 说明 |
|------|------|
| `abcx_file` | ABCX 文件路径（必需） |
| `midi_file` | MIDI 文件路径（必需） |
| `-o, --output` | 输出文件路径（可选） |
| `-v, --verbose` | 显示详细处理信息 |
| `--keep-tsv` | 保留生成的 TSV 文件 |

## 算法原理

1. **解析 ABCX 文件**：按 `|` 分割小节，提取每个小节的音符序列
2. **转换 MIDI 到 TSV**：使用 `wave-roll-studio/midi_tsv.py` 将 MIDI 转换为文本格式
3. **提取音符事件**：从 TSV 文件中提取所有音符的下键事件（格式：`NOTE:duration tick velocity`）
4. **匹配对齐**：
   - 对于每个小节，提取第一个音符
   - 在 TSV 事件序列中顺序查找匹配的音符
   - 记录匹配位置的行号

## 输出格式

输出格式为空格分隔的 `小节号:行号` 对：

```
1:16 2:64 3:110 4:144
```

表示：
- 小节 1 对应 TSV 文件第 16 行
- 小节 2 对应 TSV 文件第 64 行
- 小节 3 对应 TSV 文件第 110 行
- 小节 4 对应 TSV 文件第 144 行

## 注意事项

1. **小节定义**：小节的起始位置定义为第一个音符的下键位置
2. **音符匹配**：算法忽略八度信息，只匹配音名（C, D, E, F, G, A, B）
3. **顺序匹配**：算法按顺序匹配，不会回溯，确保时间顺序正确
4. **休止符处理**：自动跳过休止符（`z`）和不可见休止符（`x`）

## 依赖

- Python 3.6+
- `wave-roll-studio/midi_tsv.py`（项目内置）

## 示例结果

对于 Glinka 的《云雀》：

```bash
python3 align_measures.py \
    data/abc_from_xml/Glinka/The_Lark/Glinka_The_Lark.abcx \
    data/asap-dataset/Glinka/The_Lark/Denisova10M.mid
```

成功对齐了全部 76 个小节，输出：
```
1:16 2:64 3:82 4:84 5:145 6:164 7:486 8:577 9:639 10:774 11:914 12:1012 
13:1079 14:1238 15:1254 16:1261 17:1276 18:1283 19:1298 20:1390 21:1417 
22:1420 23:1422 24:1439 25:1440 26:1442 27:1472 28:1490 29:1493 30:1513 
31:1516 32:1520 33:1548 34:1646 35:1835 36:1838 37:1856 38:1940 39:2016 
40:2017 41:2019 42:2050 43:2079 44:2091 45:2097 46:2100 47:2154 48:2161 
49:2172 50:2189 51:2192 52:2193 53:2205 54:2209 55:2593 56:3198 57:3218 
58:3478 59:3587 60:3606 61:3613 62:3834 63:3841 64:3888 65:3906 66:4142 
67:4143 68:4150 69:4153 70:4157 71:4176 72:4230 73:4272 74:4327 75:4348 
76:4351
```
