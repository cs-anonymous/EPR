# PianoCoRe-A 数据处理指南

## 概述

本指南说明如何将 PianoCoRe-A 数据集处理成 SPIRE SFT 所需的格式：
- **Score**: MusicXML → ABCX
- **Performance**: MIDI + alignment → MIDI-TSV（按小节对齐）

## 数据集要求

根据 Zenodo 页面，完整的 PianoCoRe 数据集需要 16.43 GB：
- 5.14 GB: score MusicXML/MIDI 和 performance MIDI 文件 (`PianoCoRe/raw/`)
- 5.76 GB: raw alignment 文件 (`PianoCoRe/raw/`)
- 5.53 GB: refined score MIDI, performance MIDI 和 alignment 文件 (`PianoCoRe/refined/`)

## 安装依赖

```bash
pip install -r requirements_pianocore.txt
```

依赖包括：
- `pandas`: 读取 metadata.csv
- `numpy`: 处理 alignment 数据（.npz 格式）
- `tqdm`: 进度条
- `pretty_midi`: MIDI 文件处理
- `music21`: MusicXML 文件处理

## 数据下载

数据已从 Zenodo 下载：
- ✓ `PianoCoRe-1.0-raw-midi.zip` (2.7 GB)
- ⏳ `PianoCoRe-1.0-raw-alignments.zip` (下载中，预计 5.76 GB)
- ⏳ `PianoCoRe-1.0-refined.zip` (下载中，预计 5.53 GB)

## 解压数据

```bash
cd /home/sy/EPR/PianoCoRe

# 解压 raw MIDI（已完成）
unzip -q PianoCoRe-1.0-raw-midi.zip

# 解压 raw alignments（等待下载完成）
unzip -q PianoCoRe-1.0-raw-alignments.zip

# 解压 refined 数据（等待下载完成）
unzip -q PianoCoRe-1.0-refined.zip
```

解压后的目录结构：
```
PianoCoRe/
├── metadata.csv
├── composers.csv
├── PianoCoRe/
│   ├── raw/
│   │   ├── Composer_Name/
│   │   │   ├── Composition_Name/
│   │   │   │   ├── score.mxl (MusicXML)
│   │   │   │   ├── score_*.mid (Score MIDI)
│   │   │   │   ├── Performance_*.mid (Performance MIDI)
│   │   │   │   └── Performance_*_align.npz (Alignment)
│   └── refined/
│       ├── Composer_Name/
│       │   ├── Composition_Name/
│       │   │   ├── score_*_refined.mid
│       │   │   ├── Performance_*_refined.mid
│       │   │   └── Performance_*_refined_align.npz
```

## 测试处理流程

在完整处理之前，先运行测试脚本验证流程：

```bash
cd /home/sy/EPR
python3 scripts/test_process_flow.py
```

测试内容：
1. MusicXML → ABCX 转换
2. MIDI 文件加载
3. Score measure 提取

## 完整处理

### 处理少量数据（测试）

```bash
python3 scripts/process_pianocore_a_complete.py \
    --pianocore-root /home/sy/EPR/PianoCoRe \
    --output-dir /home/sy/EPR/data/pianocore_a_processed \
    --limit 10
```

### 处理全部 Tier A 数据

```bash
python3 scripts/process_pianocore_a_complete.py \
    --pianocore-root /home/sy/EPR/PianoCoRe \
    --output-dir /home/sy/EPR/data/pianocore_a_processed
```

预计处理 **157,207 对** Tier A refined 数据。

## 输出格式

输出文件：`pianocore_a_processed.jsonl`

每行是一个 JSON 对象：
```json
{
  "id": "PianoCoRe_000004",
  "composer": "Abreu,_Zequinha",
  "composition": "Tico-Tico_no_fubá",
  "abcx": "X:1\nT:Tico-Tico no fubá\n...",
  "measure_tsvs": [
    "M\t0\nN\t0\t60\t500\t80\nN\t500\t62\t500\t75\n...",
    "M\t0\nN\t0\t64\t500\t82\n..."
  ],
  "num_measures": 128
}
```

字段说明：
- `id`: PianoCoRe 数据集 ID
- `composer`: 作曲家
- `composition`: 作品名称
- `abcx`: ABCX 格式的乐谱
- `measure_tsvs`: 按小节分组的 MIDI-TSV 列表
- `num_measures`: 小节数量

### MIDI-TSV 格式

每个小节的 MIDI-TSV 格式：
```
M	0                    # Measure marker
N	<time>	<pitch>	<duration>	<velocity>
N	<time>	<pitch>	<duration>	<velocity>
...
```

- `time`: 相对于小节开始的时间（毫秒）
- `pitch`: MIDI 音高 (0-127)
- `duration`: 音符时长（毫秒）
- `velocity`: 力度 (0-127)

## 数据统计

根据 metadata.csv：
- **Tier A refined 配对数据**: 157,207 对
- **配对质量分布**:
  - Excellent (recall>0.9, precision>0.85): 96%
  - 可用于 EPR/CSR: 96%

## 处理流程说明

1. **加载数据**: 从 metadata.csv 筛选 Tier A refined 数据
2. **转换 Score**: MusicXML → ABCX（使用 `xml_to_abcx.py`）
3. **加载 Alignment**: 读取 `.npz` 文件，获取 note-level 对齐
4. **提取 Measures**: 从 MusicXML 提取小节信息（offset, duration）
5. **生成 MIDI-TSV**: 
   - 使用 alignment 将 performance notes 映射到 score notes
   - 根据 score note 的 offset 确定所属小节
   - 按小节分组 performance notes
   - 生成相对时间的 MIDI-TSV

## 注意事项

1. **内存使用**: 处理大量数据时可能需要较大内存
2. **处理时间**: 预计处理 157K 对数据需要数小时
3. **错误处理**: 脚本会跳过处理失败的数据，并在最后报告成功率
4. **数据验证**: 建议先用 `--limit 10` 测试，确认输出格式正确

## 下一步

处理完成后，数据可用于：
1. **小节级配对集** $\mathcal{D}_{\Sigma\Phi}^{M}$: 用于 EPR 和 CSR 训练
2. **未配对乐谱集** $\mathcal{D}_{\Sigma}$: 提取 ABCX 用于 Score Language 训练
3. **未配对演奏集** $\mathcal{D}_{\Phi}$: 提取 MIDI-TSV 用于 Performance Language 训练
