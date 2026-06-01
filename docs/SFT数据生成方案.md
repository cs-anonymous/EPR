# SFT 数据生成方案

## 1. 样本形式

每条样本只做一个任务：

```text
score + interpretation/performance gist → performance
```

不做多任务，不做复杂 curriculum，不做 infilling。

---

# 2. Input 格式

```text
[task]
Generate an expressive performance MIDI from the given annotated score MIDI.

[score head]
Composer: {composer}
Composition: {composition}
Movement: {movement}
Interpretation: {piece_interpretation}
Performance: {performance_concept}

<MIDI>
{12-token beat/tempo/key header}
{annotated score midi body by measures}
</MIDI>
```

数据来源于每首曲子的：
- metadata: `data/performance_S_metadata.csv`
- interpretation 中的 performance_gist: `data/miditsv/Glinka,_Mikhail/A_Farewell_to_Saint_Petersburg/10._The_Lark/piece_interpretation.json`
- annotated score midi: `data/miditsv/Glinka,_Mikhail/A_Farewell_to_Saint_Petersburg/10._The_Lark/score.annotated_score.mid.tsv`

---

# 3. Output 格式

```text
<MIDI>
{corresponding performance midi body by measures}
</MIDI>
```
数据来源于每个演奏的performance midi，例如`data/miditsv/Glinka,_Mikhail/A_Farewell_to_Saint_Petersburg/10._The_Lark/ASAP_Denisova10M_refined.mid.tsv`

---

# 4. 长度规则

固定：

```text
MAX_LENGTH = 4096
```

总长度计算：

```text
input_tokens + output_tokens <= 4096
```

切分规则：

```text
从某个小节开始，连续加入 score measure 和对应 performance measure；
只要加入下一小节后 total_tokens <= 4096，就继续加入；
超过 4096 就停止，保存当前 sample；
然后从下一个小节继续。
```

允许动态小节数：

```text
每条样本的小节数不固定
通常约 4–8 小节
```

---

# 5. Raw 数据生成

先生成完整 raw pool：

```text
sft/epr_{S,Astar}_4096_raw.jsonl
```

每条记录：

```json
{
  "sample_id": "piece001_perf003_m0008_m0014",
  "piece_id": "piece001",
  "performance_id": "perf003",
  "composer": "Mikhail Glinka",
  "composition": "The Lark",
  "movement": "",
  "measure_start": 8,
  "measure_end": 14,
  "num_measures": 7,
  "input": "...",
  "output": "...",
  "input_tokens": 1580,
  "output_tokens": 2140,
  "total_tokens": 3720,
  "split": "train"
}
```

---

# 6. 过滤规则

只保留：

```text
1. total_tokens <= 4096
2. score measures 和 performance measures 数量一致
3. input/output 非空
```


# 7. 打散

按照 `data/performance_Astar_metadata_updated.csv` 和 `data/performance_S_metadata.csv` 生成两个raw 数据

生成 raw 后再在两个来源内部整体 shuffle：

```text
sft/epr_{S,Astar}_4096_raw.jsonl
↓
sft/epr_{S,Astar}_4096_shuffled.jsonl
```

对于Round 切分中，S train 划分为2个round，Astar train 划分为3个round

目录：

```text
sft_rounds/
├── train_S1.jsonl
├── train_S2.jsonl
├── train_Astar1.jsonl
├── train_Astar2.jsonl
├── train_Astar3.jsonl
├── val.jsonl   # 对于val只保留3k个样本
└── test.jsonl
```

每个 round 不做特殊配比，不做任务混合。

---

# 9. 最终训练顺序

```text
S1 → S2 → Astar1 → Astar2 → Astar3
```

每轮接着上轮 checkpoint 继续训。

---


> 先按 4096 token 动态 pack 连续小节，生成单一 EPR raw pool；再按 piece_id 划分 train/val/test；最后将 train shuffle 后平均切成多个 round 顺序训练。
