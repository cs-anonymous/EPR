# PianoCoRe-A 数据处理总结

## 当前状态（2026-05-10）

### 数据下载进度
- ✅ **raw-midi**: 2.7 GB（已完成并解压，253,624 个文件）
- ⏳ **raw-alignments**: 1.9 GB / 5.76 GB（下载中，约 33%）
- ⏳ **refined**: 14 MB / 5.53 GB（下载中，约 0.25%）

### 依赖安装
需要安装：
```bash
pip install pretty_midi
```

或安装全部依赖：
```bash
pip install -r requirements_pianocore.txt
```

## 已完成的工作

### 1. 数据集评估报告
- 文件：`数据集评估报告_SPIRE_SFT.md`
- 内容：评估 PianoCoRe 和 score_processed 是否支撑 SPIRE SFT 设计 2.4 节的三类数据集

**关键发现**：
- PianoCoRe 提供 **188,419 对音符级配对数据**（Tier A: 157,207 对）
- 配对质量：96% 为 Excellent（recall>0.9, precision>0.85）
- 未配对演奏集：61,627 个
- score_processed 补充：4,820 个未配对乐谱（ABCX 格式）

### 2. 数据处理脚本

#### 主处理脚本
- **文件**: `scripts/process_pianocore_a_complete.py`
- **功能**:
  1. 读取 Tier A refined 配对数据（157,207 对）
  2. MusicXML → ABCX 转换
  3. MIDI + alignment → MIDI-TSV（按小节对齐）
  4. 输出 JSONL 格式

#### 测试脚本
- **文件**: `scripts/test_process_flow.py`
- **功能**: 验证处理流程（不需要 alignment）
  - MusicXML → ABCX 转换
  - MIDI 文件加载
  - Score measure 提取

#### 状态检查脚本
- **文件**: `scripts/check_pianocore_status.sh`
- **功能**: 检查下载进度、解压状态、依赖安装

### 3. 文档
- `scripts/README_PIANOCORE_PROCESSING.md`: 完整处理指南
- `requirements_pianocore.txt`: Python 依赖列表

## 处理流程

### 核心算法：MIDI + alignment → MIDI-TSV（按小节对齐）

```
1. 加载 performance MIDI 的所有 notes
2. 加载 alignment（note-level 对齐）：
   - perf_to_score[perf_idx] = score_idx
3. 加载 score 的 measure 信息（offset, duration）
4. 对每个 performance note：
   a. 通过 alignment 找到对应的 score note
   b. 根据 score note 的 offset 确定所属 measure
   c. 将 performance note 分配到该 measure
5. 对每个 measure：
   a. 计算相对时间（相对于 measure 开始）
   b. 生成 MIDI-TSV 格式
```

### 输出格式

**JSONL 文件**，每行一个 JSON 对象：
```json
{
  "id": "PianoCoRe_000004",
  "composer": "Abreu,_Zequinha",
  "composition": "Tico-Tico_no_fubá",
  "abcx": "X:1\nT:...\n...",
  "measure_tsvs": [
    "M\t0\nN\t0\t60\t500\t80\n...",
    "M\t0\nN\t0\t64\t500\t82\n..."
  ],
  "num_measures": 128
}
```

**MIDI-TSV 格式**（每个小节）：
```
M	0                    # Measure marker
N	<time>	<pitch>	<duration>	<velocity>
```
- time: 相对于小节开始的时间（毫秒）
- pitch: MIDI 音高 (0-127)
- duration: 音符时长（毫秒）
- velocity: 力度 (0-127)

## 下一步操作

### 1. 等待下载完成
监控下载进度：
```bash
bash scripts/check_pianocore_status.sh
```

### 2. 安装依赖
```bash
pip install -r requirements_pianocore.txt
```

### 3. 解压数据
```bash
cd /home/sy/EPR/PianoCoRe

# 解压 alignments（下载完成后）
unzip -q PianoCoRe-1.0-raw-alignments.zip

# 解压 refined（下载完成后）
unzip -q PianoCoRe-1.0-refined.zip
```

### 4. 运行测试
```bash
cd /home/sy/EPR
python3 scripts/test_process_flow.py
```

### 5. 处理数据

**测试处理（10 对数据）**：
```bash
python3 scripts/process_pianocore_a_complete.py \
    --pianocore-root /home/sy/EPR/PianoCoRe \
    --output-dir /home/sy/EPR/data/pianocore_a_processed \
    --limit 10
```

**完整处理（157,207 对）**：
```bash
python3 scripts/process_pianocore_a_complete.py \
    --pianocore-root /home/sy/EPR/PianoCoRe \
    --output-dir /home/sy/EPR/data/pianocore_a_processed
```

## 数据用途

处理后的数据可用于 SPIRE SFT 训练：

1. **小节级配对集** $\mathcal{D}_{\Sigma\Phi}^{M}$
   - 用于 EPR（Expressive Performance Rendering）训练
   - 用于 CSR（Controllable Score Rendering）训练
   - 数量：157,207 对（Tier A）

2. **未配对乐谱集** $\mathcal{D}_{\Sigma}$
   - 提取 ABCX 用于 Score Language 预训练
   - 来源：score_processed（4,820 个）+ PianoCoRe 配对数据的 score 部分

3. **未配对演奏集** $\mathcal{D}_{\Phi}$
   - 提取 MIDI-TSV 用于 Performance Language 预训练
   - 来源：PianoCoRe 未配对演奏（61,627 个）

## 技术细节

### 为什么需要 alignment？
- PianoCoRe 提供的是 **音符级对齐**（note-level alignment）
- 需要将 performance notes 映射到 score measures
- alignment 文件（.npz）包含：
  - `score_to_performance`: score note → performance note 映射
  - `performance_to_score`: performance note → score note 映射
  - `score_notes`: score 的音符信息
  - `performance_notes`: performance 的音符信息

### 为什么使用 refined 数据？
- refined 数据经过质量过滤和对齐优化
- Tier A 的 refined 数据质量最高（recall>0.85, precision>0.75）
- 97.8% 的配对数据已经过 refined 处理

### 小节对齐的挑战
- Performance 可能有 tempo rubato（速度变化）
- Performance 可能有装饰音、重复等
- 需要通过 alignment 确保正确的 measure 分组

## 预期结果

- **处理时间**: 预计数小时（157K 对数据）
- **输出大小**: 预计数 GB（JSONL 格式）
- **成功率**: 预计 >95%（基于 PianoCoRe 的质量分布）

## 参考资料

- PianoCoRe 论文: https://arxiv.org/abs/2503.12345（示例）
- Zenodo 数据集: https://zenodo.org/records/19186016
- SPIRE SFT 设计: `SPIRE SFT 设计.md`
