# Score MIDI → ABCX LLM 转换流程

> 将 ASAP / MAESTRO 等数据集的量化 Score MIDI 转换为干净 ABCX，用于 Perform-LM 训练数据构建。

---

## 一、整体流程

```
Score MIDI (量化)
    ↓  music21 解析 + 分批（每批 ≥10s）
ABC-like 紧凑 TSV（每行一小节，pitch.ql 格式）
    ↓  LLM batch 转换 (15-20 小节/次, few-shot)
ABCX 草稿
    ↓  人工审核修正
干净 ABCX ← Perform-LM score 侧
```

### 为什么不用纯算法转换

| 问题 | 算法转换 | LLM 转换 |
|------|---------|---------|
| 非标准时值 | 输出 `z13/6` 等乱码 | 识别为附点、三连音 |
| 调号变音 | 每个音符都加 `_`/`^` | 理解 K: 自动处理 |
| 拍号变化 | 机械插入 `[M:...]` | 理解音乐结构意义 |
| 三连音 | 无法识别 (QL≈0.333) | 输出 `(3CDE` |
| 人类可读性 | 像乱码 | 像乐谱 |

### 为什么不用 JSON 而用 ABC-like TSV

| 格式 | 2415 音符 Beethoven | Token 估算 |
|------|------|------|
| JSON (嵌套) | ~184K chars | ~46K tokens |
| ABC-like TSV | ~42K chars | ~10K tokens |
| **节省** | | **~77%** |

音符直接写为 `g0.25`（ABC 音高 + quarterLength），空格分隔，无多余分隔符。

---

## 二、输入格式：ABC-like 紧凑 TSV

### 2.1 格式定义

```
m	ts	voice	events
```

每行代表一个小节，四列用 TAB 分隔：

| 列 | 含义 | 示例 |
|----|------|------|
| `m` | 小节序号 | `1`, `2`, `15` |
| `ts` | 拍号（仅变化时写，否则 `-`） | `2/2`, `5/8`, `-` |
| `voice` | 声部 | `V1`（右手）, `V2`（左手） |
| `events` | 音符/休止序列，用**空格**分隔 | 见下方 |

**Event 格式**（ABC 音高 + quarterLength 数字，空格分隔）：

| 类型 | 格式 | 示例 |
|------|------|------|
| 音符 | `ABC音高`+`quarterLength` | `g0.25`（G4, 16分）, `c2`（C5, 半音）, `_e1.5`（Eb5, 附点4分） |
| 休止 | `z`+`quarterLength` | `z0.5`（8分休止）, `z1.5`（附点4分休止） |

**ABC 音高规则**（以 C4 = 中央 C 为基准）：

| MIDI 八度 | nameWithOctave | ABC 写法 |
|-----------|---------------|----------|
| C2        | C2            | `C,,,`   |
| C3        | C3            | `C,,`    |
| C4        | C4            | `c`      |
| C5        | C5            | `c'`     |
| C6        | C6            | `c''`    |

> 注意：C4 是**小写** `c`，C3 是**大写** `C,`，C5 是**小写** `c'`

**变音前缀**：

| 变音 | 前缀 | 示例 |
|------|------|------|
| 升（sharp） | `^` | `^G0.5` = G#3（半音） |
| 降（flat）  | `_` | `_e0.5` = Eb5（八分） |
| 还原（natural） | `=` | `=f1` = F natural（4分） |

**关键规则**：如果音符的变音已经包含在调号（K:）中，则**不写**变音前缀。只有临时变音才写 `^`/`_`/`=`。

### 2.2 TSV 样例（Beethoven Op.13 mvt.3，前 3 小节）

```
m	ts	voice	events
1	3/8	V1	g0.25 z0.25 c0.25 z0.25 d0.25 z0.25
1	3/8	V2	z1.5 C,0.5 _E,0.5 G,0.5 c0.5 C,0.5
2	2/2	V1	_e1.5 f0.5 d1.5 _e0.5
2	2/2	V2	F,0.5 G,0.5 B,0.5 C,0.5 _E,0.5 G,0.5 c0.5 _e0.5
3	-	V1	c2 z2.167 d0.25 c0.333 z0.25 b0.5 z1.5 c0.5 d0.5
3	-	V2	g0.5 _e0.5 d0.5 c0.5 g0.5 z0.5 g0.5 z0.5
```

同一份数据如果用旧格式（N|pitch|dur|ql）：
```
1	3/8	V1	N|G4|16th|0.25;R|-|16th|0.25;N|C5|16th|0.25;R|-|16th|0.25;N|D5|16th|0.25;R|-|16th|0.25
```

ABC-like 格式只有旧格式的 **40%** 字符量，且直接携带精确 quarterLength 值，不需要 LLM 做 duration type→数字的二次换算。

### 2.3 分批规则

每批包含 **≥10 秒** 的音乐内容（通过 quarterLength × BPM 换算），以完整小节为边界。如果最后一批不足 6 秒，则合并到上一批。

TSV 文件中用 `# BATCH` 注释行标记批次边界：

```
m	ts	voice	events
# BATCH 1: m1-9, 9m, 10.6s
1	3/8	V1	g0.25 z0.25 c0.25 z0.25 d0.25 z0.25
1	3/8	V2	z1.5 C,0.5 _E,0.5 G,0.5 c0.5 C,0.5
...
# BATCH 2: m10-17, 8m, 10.1s
10	-	V1	z2 d0.5 z0.5 _e0.5 f0.5
...
```

### 2.4 music21 提取脚本

```python
from music21 import converter, note as m21note

def pitch_to_abc_pitch(pitch):
    """Convert music21 pitch to ABC notation."""
    name = pitch.name        # "C", "E-", "F#"
    oct_num = pitch.octave
    acc = ""
    base = name[0]
    if len(name) > 1:
        if name[1] == '-': acc = '_'
        elif name[1] == '#': acc = '^'
    if oct_num >= 5:
        letter = base.lower()
        suffix = "'" * (oct_num - 5)
    elif oct_num == 4:
        letter = base.lower()
        suffix = ""
    else:
        letter = base.upper()
        suffix = "," * (4 - oct_num)
    return f"{acc}{letter}{suffix}"

def midi_to_abc_like_tsv(midi_path: str, min_seconds: float = 10.0,
                          min_tail_seconds: float = 6.0) -> str:
    """将 Score MIDI 转为 ABC-like 紧凑 TSV 格式（按时间分批）"""
    s = converter.parse(midi_path)

    # 获取 BPM
    bpm = 120
    for p in s.parts:
        mm = p.flatten().getElementsByClass('MetronomeMark').first()
        if mm and hasattr(mm, 'number'):
            bpm = mm.number
            break
    sec_per_ql = 60.0 / bpm

    # 收集每小节数据
    parts_list = list(s.parts)
    max_measures = max(len(list(p.getElementsByClass('Measure'))) for p in parts_list)
    measure_data = [None] * max_measures

    for pi, part in enumerate(parts_list):
        voice = f"V{pi+1}"
        measures = list(part.getElementsByClass('Measure'))
        for mi, m in enumerate(measures):
            if measure_data[mi] is None:
                ql = m.duration.quarterLength
                ts = m.timeSignature
                ts_str = f"{ts.numerator}/{ts.denominator}" if ts else "-"
                measure_data[mi] = {'num': mi+1, 'ts': ts_str, 'ql': ql, 'voices': {}}
            if measure_data[mi]['ts'] == '-' and m.timeSignature:
                measure_data[mi]['ts'] = f"{m.timeSignature.numerator}/{m.timeSignature.denominator}"

            events = []
            for el in m.flatten().notesAndRests:
                ql_str = f"{round(float(el.quarterLength), 3):g}"
                if isinstance(el, m21note.Note):
                    abc_p = pitch_to_abc_pitch(el.pitch)
                    events.append(f"{abc_p}{ql_str}")
                else:
                    events.append(f"z{ql_str}")

            measure_data[mi]['voices'][voice] = " ".join(events)
            measure_data[mi]['sec'] = measure_data[mi]['ql'] * sec_per_ql

    # 按时间分批（保证 ≥min_seconds，以完整小节为边界）
    remaining_sec = [0] * (len(measure_data) + 1)
    for i in range(len(measure_data) - 1, -1, -1):
        remaining_sec[i] = measure_data[i]['sec'] + remaining_sec[i+1]

    batches = []
    current_batch, current_sec = [], 0
    for i, md in enumerate(measure_data):
        current_batch.append(md)
        current_sec += md['sec']
        if current_sec >= min_seconds:
            remaining = remaining_sec[i+1]
            if remaining > 0 and remaining < min_tail_seconds:
                continue  # 合并剩余到当前批
            batches.append(current_batch)
            current_batch, current_sec = [], 0
    if current_batch:
        if current_sec >= min_tail_seconds:
            batches.append(current_batch)
        elif batches:
            batches[-1].extend(current_batch)
        else:
            batches.append(current_batch)

    # 生成 TSV
    lines = ["m\tts\tvoice\tevents"]
    for bi, batch in enumerate(batches):
        total_sec = sum(md['sec'] for md in batch)
        m_range = f"{batch[0]['num']}-{batch[-1]['num']}"
        lines.append(f"# BATCH {bi+1}: m{m_range}, {len(batch)}m, {total_sec:.1f}s")
        for md in batch:
            for voice in sorted(md['voices'].keys()):
                lines.append(f"{md['num']}\t{md['ts']}\t{voice}\t{md['voices'][voice]}")

    return "\n".join(lines)
```

---

## 三、LLM Prompt 设计

### 3.1 完整 Prompt 模板

```
# 转换规则：ABC-like TSV → ABCX

## 1. 输入格式

输入是 ABC-like TSV 格式，每行一个小节：
- 音符写为 `ABC音高`+`quarterLength`（如 `g0.25`, `c2`, `_e1.5`）
- 休止写为 `z`+`quarterLength`（如 `z0.5`, `z1.5`）
- 事件用空格分隔
- ABC 音高规则：C4=c, C5=c', C6=c'', C3=C,, C2=C,,,
- 变音前缀：^ (sharp), _ (flat), = (natural)

## 2. 时值映射（quarterLength → ABC 时值数字）

默认单位长度 L:1/16（16分音符 = 单位 1）。

| quarterLength | 音乐时值 | ABC 后缀数字 | 说明 |
|---------------|---------|------------|------|
| 0.25          | 16分    | 1          | 通常省略 |
| 0.5           | 8分     | 2          |      |
| 0.75          | 附点8分  | 3          | = 0.5+0.25 |
| 1.0           | 4分     | 4          |      |
| 1.5           | 附点4分  | 6          | = 1.0+0.5 |
| 2.0           | 2分     | 8          |      |
| 3.0           | 附点2分  | 12         |      |
| 4.0           | 全音符   | 16         |      |

**特殊时值**：
- 三连音 8 分（q ≈ 0.333）→ 数字 1，但需用 `(3...` 包裹三连音组
- 不规则时值 → 取最接近的标准值，人工审核时修正

**关键规则**：quarterLength × 4 = 16分音符单位数。例如 q=1.5 → 1.5×4=6。

## 3. 调号变音处理

**关键规则**：如果音符的变音已经包含在调号（K:）中，则**不写**变音前缀。
只有临时变音（accidental 不在调号内）才写 `^`/`_`/`=`。

常见调号：
- K:C → 无变音
- K:G → F#
- K:D → F#, C#
- K:F → Bb
- K:Bb → Bb, Eb
- K:Eb → Bb, Eb, Ab
- K:Ab → Bb, Eb, Ab, Db

## 4. 和弦

当多个音符在同一 onset 同时出现 → 用方括号包裹：`[C E G]`
- 方括号内的音符共享同一个时值
- 不同时值的音不能放进同一个和弦

## 5. 小节线与控制指令

- 每小节结束加 `|`
- 拍号变化：`[M:2/2]`
- 调号变化：`[K:F major]`
- 声部标记：`V:1`（右手）, `V:2`（左手）

## 6. 输出格式

X:1
T:作品名
M:初始拍号
K:初始调号
L:1/16

V:1
<右手 ABC 内容>

V:2
<左手 ABC 内容>

每行不超过 80 字符，可在小节线后换行。
```

### 3.2 Few-shot 样例设计原则

每个 few-shot 样例覆盖一个**独立的技术难点**。

| 样例 | 覆盖的难点 | 目的 |
|------|-----------|------|
| **#1** | 基础转换（音符+休止） | 建立 pitch→ABC、ql→数字 的映射 |
| **#2** | LH 八分音符序列 + 低八度逗号 | 测试八度标记 `,` |
| **#3** | 拍号变化 + 附点时值 | TS 变化影响节奏换算 |
| **#4** | LH 起始休止 | `z` 转换 |
| **#5** | 混合时值（非标准 QL） | 测试 LLM 对非标准时值的处理 |
| **#6** | 调号内变音判断 | 最关键规则：K: 内的音不加变音前缀 |

最少有效样例数：6 个。

### 3.3 实际 Few-shot 样例

```
## Few-shot Examples

### Example 1: 基础音符+休止（V1, 3/8拍）

**Input TSV:**
```
m	ts	voice	events
1	3/8	V1	g0.25 z0.25 c0.25 z0.25 d0.25 z0.25
```

**Output:**
```
V:1
G z c z d z |
```

**Notes:**
- g (小写) = C5, c (小写) = C5 → 等等，g0.25 的 g 是 G4 = G（大写）
- C4 = 小写 c, C5 = 小写 c'
- G4 = G（大写），因为 octave=4 是小写字母
- 16分音符 (q=0.25) = 1，默认省略不写
- 休止 = z

---

### Example 2: LH 八分音符序列 + 低八度（V2）

**Input TSV:**
```
m	ts	voice	events
2	-	V2	F,0.5 G,0.5 B,0.5 C,0.5 _E,0.5 G,0.5 c0.5 _e0.5
```

**Output:**
```
V:2
F,2 G,2 B,2 C,,2 _E,2 G,2 C2 E2 |
```

**Notes:**
- 8分音符 (q=0.5) = 时值数字 2
- F3/G3/B3 = 低八度 = 加逗号 `,` → `F,`, `G,`, `B,`
- C3 = 低两个八度 = `C,,`
- C4 = 中音 = `c`（无逗号）, E4 = `e`
- `_E` = Eb，在 Eb major 调号内 → 输出时去掉 `_` 前缀

---

### Example 3: 拍号变化 + 附点时值

**Input TSV:**
```
m	ts	voice	events
2	2/2	V1	_e1.5 f0.5 d1.5 _e0.5
```

**Output:**
```
V:1
[M:2/2] _e6 f2 d6 _e2 |
```

**Notes:**
- 拍号变化写 `[M:2/2]`
- q=1.5 → 1.5×4=6
- q=0.5 → 0.5×4=2

---

### Example 4: LH 起始休止

**Input TSV:**
```
m	ts	voice	events
1	4/4	V2	z1.5 C,0.5 _E,0.5 G,0.5 c0.5 C,0.5
```

**Output:**
```
V:2
z6 C,,2 E,2 G,2 C2 C,,2 |
```

**Notes:**
- q=1.5 → z6
- _E,0.5 = Eb3，在 Eb major 调号内 → `E,2`（无降号前缀）

---

### Example 5: 混合时值（含非标准 QL）

**Input TSV:**
```
m	ts	voice	events
3	-	V1	c2 z2.167 d0.25 c0.333 z0.25 b0.5 z1.5 c0.5 d0.5
```

**Output:**
```
c8 z9 d1 c1 z1 B2 z6 c2 d2 |
```

**Notes:**
- half q=2.0 → 2×4=8 → c8
- R whole q=2.167 → 2.167×4=8.668 → 非标准，取最接近的 9（人工审核修正）
- eighth q=0.333 → 0.333×4=1.333 → 非标准，取 1（人工审核时考虑是否为三连音）

---

### Example 6: 调号内变音判断

**Context:** K:Eb (调号包含 Bb, Eb, Ab — 这些音符不加变音前缀)

**Input TSV:**
```
m	ts	voice	events
2	-	V1	_e1.5
4	-	V1	^G0.5
```

**Output:**
```
e6
^G2
```

**Notes:**
- _e1.5 = Eb5，在 Eb major 调号内 → `e6`（无前缀）
- ^G0.5 = G#3，不在调号内（Eb 调号没有升 G）→ `^G2`（保留升号前缀）
```

---

## 四、完整 Prompt 拼装

### 4.1 System Prompt

```
You are a music notation expert. Convert ABC-like TSV data into ABC notation (ABCX format).
Each note is written as ABC_pitch + quarterLength (e.g. g0.25, c2, _e1.5).
Rests are z + quarterLength (e.g. z0.5, z1.5).
Follow the conversion rules precisely. Pay special attention to:
1. Key signature: notes that are in the key signature should NOT have accidental prefixes.
2. Only write ^ (sharp), _ (flat), or = (natural) for notes NOT in the key signature.
3. Duration: quarterLength × 4 = number of 16th-note units in ABC.
4. End each measure with |.
5. Write [M:...] when time signature changes.
6. Use L:1/16 as the default unit length.
```

### 4.2 User Prompt 结构

```
# Rules
<Section 3.1 的完整转换规则>

# Examples
<Section 3.3 的 6 个 few-shot 样例>

# Task
Convert the following TSV to ABCX. Output only the ABC notation, no explanations.

Context: K:Eb major (contains Bb, Eb, Ab — no accidental prefix needed for these notes)
Initial time signature: 3/8

```tsv
m	ts	voice	events
6	-	V1	g0.25 z0.25 c0.25 z0.25 d0.25 z0.25
7	-	V1	_e1.5 f0.5 d1.5 _e0.5
...
6	-	V2	z1.5 C,0.5 _E,0.5 G,0.5 c0.5 C,0.5
7	-	V2	F,0.5 G,0.5 B,0.5 C,0.5 _E,0.5 G,0.5 c0.5 _e0.5
```
```

---

## 五、批量处理策略

### 5.1 分批规则

| 参数 | 值 | 说明 |
|------|-----|------|
| 每批最短时长 | ≥10 秒 | 保证数据量充足 |
| 尾批最小阈值 | 6 秒 | 小于则合并到上一批 |
| 边界 | 完整小节 | 不在小节中间切断 |
| 上下文窗口 | header 中补充当前 K:/TS | 让 LLM 知道当前调号和拍号 |

### 5.2 处理 ASAP 全集统计

| 指标 | 值 |
|------|-----|
| 总乐谱数 | 235 首 |
| 总批次数 | 6,676 |
| 总数据行 | 68,125 |
| 总文件大小 | 4.0 MB |
| 平均每首批次数 | ~28 |
| 每次 token 成本 | ~1.5K input + ~500 output |
| 预估费用 | ~$30-60 |

### 5.3 输出文件位置

所有 TSV 文件位于 `/home/sy/2026/Music/EPR/smidi-tsv/`，文件名格式为 `{composer}_{work}_{id}.tsv`。

### 5.4 自动化脚本框架

```python
def batch_convert(midi_path: str):
    """逐批将 Score MIDI 转成 ABCX"""
    tsv_data = midi_to_abc_like_tsv(midi_path, min_seconds=10.0)

    # 解析 TSV
    lines = tsv_data.strip().split('\n')
    data_lines = [l for l in lines if l and not l.startswith('#') and not l.startswith('m\t')]

    # 获取规则 + few-shot（从模板文件读取）
    rules = load_template("conversion_rules.md")
    examples = load_template("few_shot_examples.md")

    # 按批处理（BATCH 注释行标记了边界）
    current_batch = []
    all_abc = []
    for line in lines:
        if line.startswith('# BATCH'):
            if current_batch:
                prompt = build_prompt(rules, examples, current_batch)
                all_abc.append(call_llm(prompt, temperature=0.1))
            current_batch = []
        elif line and not line.startswith('m\t'):
            current_batch.append(line)

    if current_batch:
        prompt = build_prompt(rules, examples, current_batch)
        all_abc.append(call_llm(prompt, temperature=0.1))

    return merge_abc(all_abc)
```

---

## 六、人工审核指南

### 6.1 审核重点

| 检查项 | 常见问题 | 修正方法 |
|--------|---------|---------|
| **调号变音** | LLM 多写或少写 `^`/`_` | 对照 K: 检查 |
| **时值数字** | 非标准 QL 的近似值 | 改为精确值 |
| **三连音** | LLM 可能漏掉 `(3...` | 补充括号 |
| **小节总时值** | 不等于拍号要求 | 修正错误时值 |
| **八度标记** | C4/c/C', 大小写/逗号混淆 | 检查音高范围 |
| **和弦** | 不同时值的音被错误合并 | 拆开 |

### 6.2 快速验证

每个小节的 ABC 总时值数字之和应该等于拍号对应的 16 分音符单位数：
- 3/8 → 6 个16分单位
- 4/4 → 16 个16分单位
- 2/2 → 32 个16分单位

```python
def verify_measure(abc_line: str, ts_numerator: int, ts_denominator: int) -> bool:
    """验证小节总时值是否匹配拍号"""
    expected = (ts_numerator * 4) // ts_denominator * 4  # 转为16分单位数
    # 解析 ABC 中的时值数字，求和验证
    ...
```

### 6.3 审核界面建议

```
┌─────────────────────────────────────────────┐
│ M6 (3/8)  │  G z c z d z                    │
│           │                                 │
│           │  [Accept] [Edit] [Skip]         │
├─────────────────────────────────────────────┤
│  TSV 原始数据:                               │
│  6  -  V1  g0.25 z0.25 c0.25 z0.25 d0.25 z0.25 │
│  Total q=1.5 ✓ (3/8 = 1.5 beats)           │
└─────────────────────────────────────────────┘
```

---

## 七、Pipeline 总结

```
┌──────────────┐
│ Score MIDI   │  ASAP midi_score.mid
│ (量化)        │  235 首乐谱，已量化到节拍网格
└──────┬───────┘
       │ music21 解析 + 时间分批（≥10s）
       ▼
┌──────────────────────────────┐
│ ABC-like 紧凑 TSV             │  每行一小节, pitch.ql 格式
│ (smidi-tsv/)                 │  ~4.0 MB 总计
└──────┬───────┘
       │ LLM batch (per BATCH, ~10-15s each)
       │ few-shot prompt (~1.5K tokens)
       ▼
┌──────────────┐
│ ABCX Draft   │  人类可读，带 K:/M:/V: 标记
│ (需要审核)    │  ~95% 准确度
└──────┬───────┘
       │ 人工审核修正
       ▼
┌──────────────┐
│ Clean ABCX   │  100% 精确
│ ← Perform-LM │  score 侧训练数据
│  训练数据     │
└──────────────┘
```

---

*最后更新: 2026-05-01*
