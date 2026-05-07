# ABCX 乐句切割设计方案

## 一、目标

将 ABCX 格式的乐谱按乐句（phrase）切割，每个乐句包含：
1. **ABCX 头部**（完整的元数据）
2. **上一个小节内容**（如果存在，用于提供上下文）
3. **当前乐句内容**（不含换行符，连续的音乐片段）

**约束条件：**
- 理想乐句长度：4-8 个小节
- 超过 8 个小节时必须切割
- 少于 4 个小节的片段尽量与前后拼接，避免孤段

---

## 二、乐理启发式算法

### 2.1 乐句边界判断规则（优先级从高到低）

#### **规则 1：强制边界（优先切割）**
- **反复记号**：`:|`、`|:`、`::`、`||`（双小节线）
- **终止线**：`|]`
- **多声部长休止**：大部分声部（≥ 75%）同时出现 ≥ 2 拍的休止符
  - 权重根据休止声部比例动态调整：`score += 100 * (休止声部数 / 总声部数)`
- **速度/拍号变化**：`[Q:]`、`[M:]`、`[L:]` 标记
- **段落标记**：`P:A`、`P:B` 等

#### **规则 2：强乐句边界（优先切割点）**
- **力度突变**：`!pp!` → `!ff!`、`!f!` → `!p!` 等跨越 2 级以上的力度变化
- **和声终止式**（权重适中，因为分析可能不可靠）：
  - 优先使用和弦标记：分析 `"G7"` → `"C"` 等序列
  - 和弦标记缺失时（常态），进行简单的和声分析：
    - 统计小节内所有声部的音高分布
    - 识别可能的三和弦结构（根音-三度-五度）
    - 检测 V-I 或 I-V 进行
  - 完全终止（V-I）：score += 40
  - 半终止（I-V）：score += 30
- **长时值音符**：多个声部出现 ≥ 1 小节的长音
  - 权重根据长音声部比例调整：`score += 50 * (长音声部数 / 总声部数)`
- **旋律下行到主音**：最高声部（V1）结束在调性主音且为下行趋势

#### **规则 3：弱乐句边界（次优切割点）**
- **旋律重复模式开始**：检测到与前 2-4 小节相似的旋律模式（音高序列相似度 > 70%）
- **节奏型变化**：连续 2 小节以上的节奏型突然改变
- **音域跳跃**：最高声部出现 > 八度的跳进
- **装饰音密集区结束**：连续装饰音（`~`、`{}`）后的第一个"干净"小节

#### **规则 4：避免切割的情况（软约束）**
- **圆滑线/连音线跨小节**：`(` 开始但 `)` 未闭合
- **渐强/渐弱进行中**：`!crescendo(!` 开始但 `!crescendo)!` 未结束
- **范围型标记未闭合**：`@[V1:cr1:crescendo(` 未配对
- **连音符跨小节**：`(3` 等连音符组未完成

**注意**：这些是软约束，降低切割得分但不绝对禁止。如果达到 8 个小节仍未找到合适切割点，即使有未闭合标记也必须强制切割。

---

### 2.2 切割算法流程

```
输入：ABCX 文件
输出：乐句列表（每个乐句包含头部 + 上一小节 + 当前乐句）

1. 解析 ABCX 文件
   - 提取头部（X: 到 K: 之间的所有行）
   - 按小节分割曲体（以 `|` 为分隔符）
   - 记录每个小节的行号、内容、和弦标记、力度标记等

2. 为每个小节计算"边界得分"
   score = 0
   if 满足规则1: score += 动态权重（根据声部比例）
   if 满足规则2: score += 30-50（和声分析权重适中）
   if 满足规则3: score += 20   # 弱乐句边界
   if 满足规则4: score -= 50   # 降低得分但不绝对禁止

3. 自适应切割策略
   - 遍历小节，累计长度
   - 在 4-8 小节范围内，选择边界得分最高的点切割
   - 不设固定阈值（如 score >= 50），而是相对比较
   - 当 length = 8 时，必须在当前范围内选择最佳点强制切割（即使得分很低）

4. 孤段处理
   for each segment:
       if len(segment) < 4:
           if 可以与前一段合并 且 合并后 <= 10:
               合并到前一段
           elif 可以与后一段合并 且 合并后 <= 10:
               合并到后一段
           else:
               保持独立（标记为"短乐句"）

5. 生成输出
   for each phrase:
       output = header + previous_bar + phrase_content
```

---

## 三、实现细节

### 3.1 小节解析

```python
class Bar:
    def __init__(self, content: str, index: int):
        self.content = content          # 原始内容
        self.index = index              # 小节编号
        self.voices = []                # 按 ; 分割的声部列表
        self.chords = []                # 和弦标记列表（如 "Cm", "G7"）
        self.dynamics = []              # 力度标记列表（如 !pp!, !f!）
        self.tempo_changes = []         # 速度变化（如 [Q:1/4=60]）
        self.has_repeat = False         # 是否包含反复记号
        self.has_double_bar = False     # 是否包含双小节线
        self.max_rest_duration = 0      # 最长休止时值
        self.max_note_duration = 0      # 最长音符时值
        self.has_unclosed_slur = False  # 是否有未闭合的圆滑线
        self.has_unclosed_range = False # 是否有未闭合的范围标记
```

### 3.2 和声分析

```python
def detect_cadence(bar1: Bar, bar2: Bar, key: str) -> tuple[str, float]:
    """
    检测终止式类型
    返回: (类型, 置信度)
    类型: "perfect" (完全终止), "half" (半终止), "deceptive" (阻碍终止), None
    置信度: 0.0-1.0，表示分析的可靠性
    """
    # 优先使用和弦标记（高置信度）
    if bar1.chords and bar2.chords:
        cadence_type = analyze_chord_progression(bar1.chords, bar2.chords, key)
        return cadence_type, 0.9  # 高置信度
    
    # 和弦标记缺失时，进行简单的音高统计分析（低置信度）
    pitches1 = extract_all_pitches(bar1)  # 提取所有声部的音高
    pitches2 = extract_all_pitches(bar2)
    
    # 识别可能的和弦结构
    chord1 = infer_chord_from_pitches(pitches1, key)
    chord2 = infer_chord_from_pitches(pitches2, key)
    
    if chord1 and chord2:
        cadence_type = analyze_chord_progression([chord1], [chord2], key)
        return cadence_type, 0.5  # 中等置信度
    
    return None, 0.0

def infer_chord_from_pitches(pitches: list, key: str) -> str:
    """
    从音高集合推断可能的和弦
    使用简单的三和弦匹配（根音-三度-五度）
    """
    if not pitches:
        return None
    
    # 统计音高类别（忽略八度）
    pitch_classes = [p % 12 for p in pitches]
    pitch_counts = Counter(pitch_classes)
    
    # 尝试匹配主和弦、属和弦、下属和弦
    tonic = note_to_pitch(key[0])
    dominant = (tonic + 7) % 12
    subdominant = (tonic + 5) % 12
    
    # 检查是否包含三和弦的三个音
    if matches_triad(pitch_classes, tonic):
        return "I"
    elif matches_triad(pitch_classes, dominant):
        return "V"
    elif matches_triad(pitch_classes, subdominant):
        return "IV"
    
    return None
```

### 3.3 旋律分析

```python
def analyze_melody_contour(bar: Bar) -> dict:
    """
    分析旋律轮廓（综合所有声部，重点关注最高声部 V1）
    装饰音被忽略，只分析主要音符
    """
    v1_notes = extract_notes(bar.voices[0], ignore_ornaments=True)
    
    return {
        "range": max(v1_notes) - min(v1_notes) if v1_notes else 0,
        "last_note": v1_notes[-1] if v1_notes else None,
        "direction": "down" if len(v1_notes) >= 2 and v1_notes[-1] < v1_notes[0] else "up",
        "has_leap": any(abs(v1_notes[i+1] - v1_notes[i]) > 12 for i in range(len(v1_notes)-1)) if len(v1_notes) > 1 else False,
        "pattern": compute_pattern_hash(v1_notes)  # 用于检测重复
    }

def extract_notes(voice_content: str, ignore_ornaments: bool = True) -> list:
    """
    从声部内容提取音高序列
    ignore_ornaments=True 时忽略 ~, {}, 等装饰音
    """
    # 实现细节：解析 ABC 音符，过滤装饰音
    pass
```

### 3.4 边界得分计算

```python
def compute_boundary_score(bar: Bar, next_bar: Bar, key: str, time_sig: str, total_voices: int) -> float:
    """
    计算小节边界的切割得分
    返回浮点数，支持动态权重调整
    """
    score = 0.0
    
    # 规则 1：强制边界（动态权重）
    if bar.has_repeat or bar.has_double_bar:
        score += 100
    
    # 多声部长休止：根据休止声部比例动态调整
    rest_voices = count_voices_with_long_rest(bar, time_sig)
    if rest_voices > 0:
        rest_ratio = rest_voices / total_voices
        score += 100 * rest_ratio  # 0-100 之间
    
    if bar.tempo_changes or bar.meter_changes:
        score += 100
    
    # 规则 2：强乐句边界（考虑置信度）
    cadence_type, confidence = detect_cadence(bar, next_bar, key)
    if cadence_type == "perfect":
        score += 40 * confidence  # 和声分析权重适中
    elif cadence_type == "half":
        score += 30 * confidence
    
    # 长时值音符：根据声部比例动态调整
    long_note_voices = count_voices_with_long_note(bar, time_sig)
    if long_note_voices > 0:
        long_note_ratio = long_note_voices / total_voices
        score += 50 * long_note_ratio
    
    dynamics_jump = compute_dynamics_jump(bar.dynamics, next_bar.dynamics)
    if dynamics_jump >= 2:
        score += 50
    
    melody = analyze_melody_contour(bar)
    if melody["direction"] == "down" and is_tonic(melody["last_note"], key):
        score += 40
    
    # 规则 3：弱乐句边界
    if melody["has_leap"]:
        score += 20
    
    # 规则 4：避免切割（软约束，降低得分）
    if bar.has_unclosed_slur or bar.has_unclosed_range:
        score -= 50  # 不是绝对禁止，只是降低优先级
    
    return score
```

---

## 四、输出格式

### 4.1 单个乐句结构

```
{
    "phrase_id": 1,
    "bar_range": [1, 6],           # 小节范围（起始小节号，结束小节号）
    "bar_count": 6,                # 小节数量（即在当前乐句之前的 "|" 数量 + 1）
    "header": "X:1\nT:...\n...",   # 完整头部
    "previous_bar": "| ... |",     # 上一个小节（如果存在）
    "content": "| ... | ... | ..." # 当前乐句（去除换行符，连续内容）
}
```

### 4.2 示例输出

```json
[
    {
        "phrase_id": 1,
        "bar_range": [1, 6],
        "bar_count": 6,
        "header": "X:1\nT:Étude in E Major\n%%score { ( 1 3 4 ) | ( 2 5 ) }\nL:1/16\nQ:1/4=100\nM:2/4\nK:E",
        "previous_bar": null,
        "content": "!p!\"^Lento, ma non troppo 1)\" (B,2 ; z2 ; z2 ; z2 ; z2 | E2DE) (F4- ; G,B,G,B, A,B,A,B, ; z4 D4- ; E,,B,,2B,, B,,,B,,2B,, ; E,,4 B,,,4 | FG GF) ([EG-]4 ; A,B,A,B, G,B,G,B, ; D2D2 z4 ; B,,,B,,2B,, E,,B,,2B,, ; B,,,4 E,,4 | GA AG) (c2>B2 ; G,EB,E DAB,D ; z8 ; E,,B,,2B,, B,,,B,,2B,, ; E,,4 B,,,4 | AGDE) (!>!F4- ; B,EG,B, ([A,C][B,D][A,C][B,D] ; z8 ; E,,B,,2B,, B,,,B,,2B,, ; E,,4 B,,,4 | FG GF !>!E4) ; [A,C][B,D][A,C][B,D]) G,B,G,B, ; z8 ; B,,,B,,2B,, E,,B,,2B,, ; B,,,4 E,,4 |"
    },
    {
        "phrase_id": 2,
        "bar_range": [7, 12],
        "bar_count": 6,
        "header": "X:1\nT:Étude in E Major\n%%score { ( 1 3 4 ) | ( 2 5 ) }\nL:1/16\nQ:1/4=100\nM:2/4\nK:E",
        "previous_bar": "FG GF !>!E4) ; [A,C][B,D][A,C][B,D]) G,B,G,B, ; z8 ; B,,,B,,2B,, E,,B,,2B,, ; B,,,4 E,,4 |",
        "content": "!<(! (GAFG!<)! ABGA ; =DEDE CECE ; z8 ; E,,E,2E, A,,E,2E, ; E,,4 A,,4 | c2) (!>!F4[Q:1/4=38]{/^A} (!>!GF-) ; CECE\"_stretto\" B,EB,E ; z8 ; A,,F,2F, B,,F,2F, ; A,,4 B,,4 | ..."
    }
]
```

---

## 五、边界情况处理

### 5.1 文件开头
- 第一个乐句的 `previous_bar` 为 `null`

### 5.2 文件结尾
- 最后一个乐句可能少于 4 个小节（如尾奏），保持独立

### 5.3 极短片段（< 4 小节）
- 优先与前一段合并（如果合并后 ≤ 10 小节）
- 其次与后一段合并
- 如果无法合并且该片段有明确的音乐意义（如引子、尾奏），保持独立并标记

### 5.4 极长片段（> 8 小节）
- 在 4-8 小节范围内选择得分最高的点切割
- 如果所有候选点得分都很低（说明音乐连续性强），仍然选择相对最高的点
- 即使有未闭合的范围标记，达到 8 小节也必须强制切割

---

## 六、可配置参数

```python
class PhraseSegmentationConfig:
    min_phrase_length = 4      # 最小乐句长度
    max_phrase_length = 8      # 最大乐句长度
    merge_threshold = 10       # 合并后的最大长度
    
    # 边界得分权重
    weight_repeat = 100
    weight_long_rest = 100
    weight_tempo_change = 100
    weight_perfect_cadence = 60
    weight_half_cadence = 50
    weight_long_note = 50
    weight_dynamics_jump = 50
    weight_tonic_descent = 40
    weight_leap = 20
    weight_unclosed_mark = -100
```

---

## 七、测试用例

### 7.1 正常情况
- 输入：8 小节的简单旋律，中间有明确的半终止
- 期望：切割为 4+4 两个乐句

### 7.2 反复记号
- 输入：`|: A | B | C | D :|`
- 期望：在 `:|` 处切割

### 7.3 孤段合并
- 输入：6 小节 + 2 小节 + 8 小节
- 期望：(6+2) + 8 = 8 + 8

### 7.4 未闭合标记
- 输入：小节 4 开始 `!crescendo(!`，小节 6 结束 `!crescendo)!`
- 期望：不在小节 4-6 之间切割

---

## 八、实现优先级

1. **Phase 1（核心功能）**
   - 小节解析
   - 规则 1（强制边界）
   - 规则 4（禁止切割）
   - 基本切割逻辑（4-8 小节）

2. **Phase 2（乐理增强）**
   - 规则 2（和声分析、力度变化）
   - 规则 3（旋律分析）
   - 孤段合并

3. **Phase 3（优化）**
   - 可配置参数
   - 边界情况处理
   - 测试用例验证

---

## 九、设计确认（已解决）

根据评审反馈，以下设计已确认：

1. **和弦标记缺失**：✅ 需要实现简单的和声分析（基于音高统计），但权重适中（30-40），因为可能不可靠
2. **多声部边界一致性**：✅ ABCX 强制要求多声部时值一致，边界判断综合考虑所有声部特征
3. **装饰音处理**：✅ 忽略装饰音，只分析主要音符；切割基本在小节线后，装饰音不影响
4. **输出格式**：✅ 去除换行符，但记录小节编号（`bar_count` = 当前小节之前的 "|" 数量 + 1）
5. **切割策略**：✅ 自适应策略，在 4-8 小节范围内选择得分最高的点，不设固定阈值
6. **长休止规则**：✅ 根据休止声部比例动态调整权重（`score += 100 * 休止比例`）
7. **避免切割**：✅ 软约束，降低得分但不绝对禁止；达到 8 小节必须强制切割

---

## 十、参考资料

- ABCX 扩展格式规范 v0.3
- ABC 标准 v2.1
- 音乐理论：终止式、乐句结构、旋律分析
