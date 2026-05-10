#!/bin/bash
# 检查 PianoCoRe 数据集状态

echo "=========================================="
echo "PianoCoRe 数据集状态检查"
echo "=========================================="
echo ""

cd /home/sy/EPR/PianoCoRe

echo "1. 压缩包下载状态"
echo "------------------------------------------"
echo "raw-midi:       $(ls -lh PianoCoRe-1.0-raw-midi.zip 2>/dev/null | awk '{print $5}') / 2.7 GB"
echo "raw-alignments: $(ls -lh PianoCoRe-1.0-raw-alignments.zip 2>/dev/null | awk '{print $5}') / 5.76 GB"
echo "refined:        $(ls -lh PianoCoRe-1.0-refined.zip 2>/dev/null | awk '{print $5}') / 5.53 GB"
echo ""

echo "2. 解压状态"
echo "------------------------------------------"
if [ -d "PianoCoRe/raw" ]; then
    raw_count=$(find PianoCoRe/raw -type f | wc -l)
    echo "✓ raw/ 已解压 ($raw_count 个文件)"
else
    echo "✗ raw/ 未解压"
fi

if [ -d "PianoCoRe/refined" ]; then
    refined_count=$(find PianoCoRe/refined -type f | wc -l)
    echo "✓ refined/ 已解压 ($refined_count 个文件)"
else
    echo "✗ refined/ 未解压"
fi
echo ""

echo "3. 关键文件检查"
echo "------------------------------------------"
if [ -f "metadata.csv" ]; then
    total_rows=$(wc -l < metadata.csv)
    echo "✓ metadata.csv 存在 ($total_rows 行)"
else
    echo "✗ metadata.csv 不存在"
fi

# 检查 alignment 文件
align_count=$(find PianoCoRe/raw -name "*.npz" 2>/dev/null | wc -l)
if [ $align_count -gt 0 ]; then
    echo "✓ raw alignment 文件: $align_count 个"
else
    echo "✗ raw alignment 文件未找到"
fi

refined_align_count=$(find PianoCoRe/refined -name "*.npz" 2>/dev/null | wc -l)
if [ $refined_align_count -gt 0 ]; then
    echo "✓ refined alignment 文件: $refined_align_count 个"
else
    echo "✗ refined alignment 文件未找到"
fi
echo ""

echo "4. 下载进程"
echo "------------------------------------------"
wget_procs=$(ps aux | grep wget | grep -v grep | grep PianoCoRe)
if [ -n "$wget_procs" ]; then
    echo "⏳ 下载进行中:"
    echo "$wget_procs" | awk '{print "  ", $11, $12, $13}'
else
    echo "✓ 无下载进程"
fi
echo ""

echo "5. 依赖检查"
echo "------------------------------------------"
python3 -c "import pandas; print('✓ pandas')" 2>/dev/null || echo "✗ pandas 未安装"
python3 -c "import numpy; print('✓ numpy')" 2>/dev/null || echo "✗ numpy 未安装"
python3 -c "import pretty_midi; print('✓ pretty_midi')" 2>/dev/null || echo "✗ pretty_midi 未安装"
python3 -c "import music21; print('✓ music21')" 2>/dev/null || echo "✗ music21 未安装"
python3 -c "import tqdm; print('✓ tqdm')" 2>/dev/null || echo "✗ tqdm 未安装"
echo ""

echo "=========================================="
echo "建议操作"
echo "=========================================="

# 检查是否需要安装依赖
python3 -c "import pretty_midi" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "1. 安装依赖: pip install -r requirements_pianocore.txt"
fi

# 检查是否需要解压
if [ ! -d "PianoCoRe/refined" ] && [ -f "PianoCoRe-1.0-refined.zip" ]; then
    refined_size=$(stat -c%s PianoCoRe-1.0-refined.zip)
    if [ $refined_size -gt 1000000000 ]; then  # > 1GB
        echo "2. 解压 refined: unzip -q PianoCoRe-1.0-refined.zip"
    fi
fi

if [ $align_count -eq 0 ] && [ -f "PianoCoRe-1.0-raw-alignments.zip" ]; then
    align_size=$(stat -c%s PianoCoRe-1.0-raw-alignments.zip)
    if [ $align_size -gt 1000000000 ]; then  # > 1GB
        echo "3. 解压 alignments: unzip -q PianoCoRe-1.0-raw-alignments.zip"
    fi
fi

# 检查是否可以运行测试
if [ -d "PianoCoRe/raw" ]; then
    python3 -c "import pretty_midi" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "4. 运行测试: python3 scripts/test_process_flow.py"
    fi
fi

# 检查是否可以运行完整处理
if [ -d "PianoCoRe/refined" ] && [ $refined_align_count -gt 0 ]; then
    echo "5. 运行完整处理: python3 scripts/process_pianocore_a_complete.py --pianocore-root /home/sy/EPR/PianoCoRe --output-dir /home/sy/EPR/data/pianocore_a_processed --limit 10"
fi

echo ""
