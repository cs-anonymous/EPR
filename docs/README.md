# ABCX-MIDI 配对数据集生成方案

> 基于乐谱结构的切割方案，输出 JSON 格式，适合构建 fine-grained EPR 数据集

## Related docs

- [Language CPT Training Notes](./CPT_LANGUAGE_TRAINING.md): language CPT 的当前默认配置，以及 `flash_attn` / `packing` 的测速结论

## 数据结构

**核心设计**：
- 一个作品有 **1 个 ABCX** 文件（乐谱）
- 一个作品有 **多个 MIDI** 文件（不同演奏者的演奏）
- 每个 **(ABCX, MIDI) pair** 生成 **1 个 JSON** 文件

**目录结构**：
- 支持多层目录结构（Composer/Work/SubWork）
- ABCX 和 MIDI 目录结构完全一致
- 自动匹配对应的演奏 MIDI

**示例**：
```
Glinka/The_Lark/
├── Glinka_The_Lark.abcx          # 乐谱
├── Denisova10M.mid               # 演奏1
└── Kleisen07M.mid                # 演奏2

生成：
├── Glinka_The_Lark_Denisova10M.json   # ABCX + 演奏1
└── Glinka_The_Lark_Kleisen07M.json    # ABCX + 演奏2

Chopin/Etudes_op_25/12/
├── Chopin_Etudes_op_25_12.abcx   # 乐谱
├── Atzinger03.mid                # 演奏1
└── Kunz03.mid                    # 演奏2

生成：
├── Chopin_Etudes_op_25_12_Atzinger03.json
└── Chopin_Etudes_op_25_12_Kunz03.json
```

## 快速开始

```bash
# 测试模式：只处理 Glinka/The_Lark
python scripts/generate_paired_dataset.py --test --output-dir output/test

# 批量处理整个 ASAP 数据集
python scripts/generate_paired_dataset.py \
    --data-dir data \
    --output-dir output/dataset
```

## 核心改进

### 1. 从启发式切割到基于乐谱切割

| 方案 | 切割依据 | 音乐完整性 | 可解释性 |
|------|---------|-----------|---------|
| 启发式切割（wave-roll-studio） | 音符间隙、踏板释放 | ❌ 可能在乐句中间切断 | ❌ 低 |
| 基于乐谱切割（本方案） | 小节边界、乐句标记、重复记号 | ✅ 保证乐句完整 | ✅ 高 |

### 2. 从多文件到单 JSON 文件

| 格式 | 文件数量 | 加载方式 | Header 存储 | 适合场景 |
|------|---------|---------|------------|---------|
| 多文件格式 | 每个片段 2 个文件 | 需要匹配文件名 | 每个片段重复 | 大规模数据集 |
| JSON 格式（本方案） | 每个作品 1 个文件 | 直接 `json.loads()` | 共享 header | 中小规模数据集 |

## 输出格式

每个 (ABCX, MIDI) pair 生成一个 JSON 文件，包含：
- **完整的 ABCX header**：可以重建任何片段的完整 ABCX
- **完整的 MIDI-TSV header**：可以重建任何片段的完整 MIDI-TSV
- **多个 segments**：每个片段包含 ABCX 和 MIDI-TSV 的曲体部分

```json
{
  "metadata": {
    "title": "The Skylark",
    "composer": "Mikhail Glinka",
    "performer": "Denisova10M",
    "num_measures": 76,
    "num_segments": 5
  },
  "abcx_header": "X:1\nT:The Skylark\nM:4/4\nL:1/16\nQ:1/4=63\nK:Db\n...",
  "midi_tsv_header": [
    "# midi-tsv v0.1",
    "# source=Denisova10M.mid",
    "# tpq=480",
    "..."
  ],
  "segments": [
    {
      "id": 1,
      "start_measure": 1,
      "end_measure": 12,
      "duration_seconds": 28.5,
      "abcx_body": "第1-12小节的ABCX内容...",
      "midi_tsv_data": "第1-12小节的MIDI-TSV数据..."
    }
  ]
}
```

**文件命名**：`Composer_Work_Performer.json`
- 例如：`Glinka_The_Lark_Denisova10M.json`

**输出目录结构**：
```
output/dataset/
├── Glinka/
│   ├── Glinka_The_Lark_Denisova10M.json
│   └── Glinka_The_Lark_Kleisen07M.json
├── Beethoven/
│   ├── Beethoven_Sonata01-1_Performer1.json
│   └── Beethoven_Sonata01-1_Performer2.json
└── dataset_stats.json
```

## 切割策略

基于音乐结构的优先级（得分越高越优先）：

| 优先级 | 切割点类型 | 得分 | 说明 |
|-------|----------|------|------|
| 1 | 重复记号结束 `:\|` | 100 | 重复段落的自然边界 |
| 2 | 终止线 `\|]` | 90 | 乐曲或段落结束 |
| 3 | 双小节线 `\|\|` | 80 | 段落分隔 |
| 4 | 乐句结束（圆滑线、fermata） | 70 | 乐句自然结束 |
| 5 | 长休止后 | 60 | 音乐停顿 |
| 6 | 接近目标时长 | 0-50 | 时长越接近得分越高 |

**参数**：
- `--min-measures`: 最小小节数（默认 8）
- `--max-measures`: 最大小节数（默认 16）
- `--target-seconds`: 目标时长（默认 30 秒）

## 下游使用

### Python 读取

```python
import json
from pathlib import Path

# 读取数据
data = json.loads(Path("output/dataset/Glinka/The_Lark.json").read_text())

# 遍历所有片段
for segment in data['segments']:
    # 重建完整的 ABCX
    full_abcx = data['abcx_header'] + '\n\n' + segment['abcx_body']
    
    # 重建完整的 MIDI-TSV
    full_midi_tsv = '\n'.join(data['midi_tsv_header']) + '\n\n' + segment['midi_tsv_data']
```

### PyTorch 数据加载器

```python
from torch.utils.data import Dataset

class ABCXMIDIDataset(Dataset):
    def __init__(self, json_dir):
        self.samples = []
        for json_path in Path(json_dir).rglob("*.json"):
            if json_path.name == "dataset_stats.json":
                continue
            data = json.loads(json_path.read_text())
            for segment in data['segments']:
                self.samples.append({
                    'abcx_header': data['abcx_header'],
                    'abcx_body': segment['abcx_body'],
                    'midi_tsv_header': data['midi_tsv_header'],
                    'midi_tsv_data': segment['midi_tsv_data']
                })
    
    def __getitem__(self, idx):
        s = self.samples[idx]
        return {
            'abcx': s['abcx_header'] + '\n\n' + s['abcx_body'],
            'midi_tsv': '\n'.join(s['midi_tsv_header']) + '\n\n' + s['midi_tsv_data']
        }
```

## 实现模块

```
scripts/
├── abcx_parser.py               # ABCX 解析器
├── score_based_segmentation.py  # 切割算法
└── generate_paired_dataset.py   # 配对数据集生成器
```

## 统计信息

处理完成后会生成 `dataset_stats.json`：

```json
{
  "total_abcx_files": 235,
  "total_pairs": 1067,
  "total_segments": 15234,
  "avg_segments_per_pair": 14.3
}
```

- `total_abcx_files`: 总作品数（ABCX 文件数）
- `total_pairs`: 总配对数（ABCX-MIDI pairs）
- `total_segments`: 总片段数
- `avg_segments_per_pair`: 平均每个配对的片段数

## 后续改进

1. 使用 ASAP 数据集的 `asap_annotations.json` 获取精确对齐信息
2. 完善 MIDI 解析，处理拍号变化和变速
3. 改进时值计算，处理三连音等复杂节奏

---

*最后更新: 2026-05-06*
