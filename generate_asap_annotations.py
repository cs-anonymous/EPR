#!/usr/bin/env python3
"""
完整复现ASAP数据集的annotation生成流程

支持单个文件处理和批量处理两种模式：
- 单个文件：指定 --score-midi 和 --perf-midi
- 批量处理：指定 --asap-root（默认模式）

流程：
1. 从MIDI Score生成score annotations (beat/downbeat/time signature/key signature)
2. 使用Nakamura对齐算法生成score-performance对应关系
3. 从对应关系生成performance annotations
"""

import pretty_midi as pm
import pandas as pd
import numpy as np
import math
from pathlib import Path
import subprocess
import argparse
import sys


# ============================================================================
# Part 1: MIDI Score Annotations生成
# ============================================================================

def midi_to_beat_annotations(midi_path):
    """从MIDI文件提取beat annotations"""
    mididata = pm.PrettyMIDI(str(midi_path))
    beats = mididata.get_beats()

    # 计算理论beat长度（使用中间部分避免开头的短beat）
    if len(beats) > 40:
        b_len = beats[40] - beats[39]
    else:
        b_len = beats[2] - beats[1] if len(beats) > 2 else 0.5

    beat_dict = {}
    for i, b in enumerate(beats[:-1]):
        # 检查是否是规则的beat
        if math.isclose(beats[i+1] - beats[i], b_len, rel_tol=1e-2):
            beat_dict[b] = "b"
        else:
            beat_dict[b] = "bW"  # Warning: irregular beat

    return beat_dict


def midi_to_downbeat_annotations(midi_path):
    """从MIDI文件提取downbeat annotations"""
    mididata = pm.PrettyMIDI(str(midi_path))
    downbeats = mididata.get_downbeats()

    # 计算理论downbeat长度
    if len(downbeats) > 2:
        db_len = downbeats[2] - downbeats[1]
    else:
        db_len = 2.0

    downbeat_dict = {}
    for i, db in enumerate(downbeats[:-1]):
        # 检查是否是规则的downbeat
        if math.isclose(downbeats[i+1] - downbeats[i], db_len, rel_tol=1e-2):
            downbeat_dict[db] = "db"
        else:
            downbeat_dict[db] = "dbW"  # Warning: irregular downbeat

    return downbeat_dict


def midi_to_time_signature_changes(midi_path):
    """从MIDI文件提取拍号变化"""
    mididata = pm.PrettyMIDI(str(midi_path))
    ts_changes = []

    for ts in mididata.time_signature_changes:
        ts_string = f"{ts.numerator}/{ts.denominator}"
        ts_changes.append((ts.time, ts_string))

    # 去重
    ts_changes_unique = []
    for i, ts in enumerate(ts_changes):
        if i == 0 or ts[1] != ts_changes[i-1][1]:
            ts_changes_unique.append(ts)

    return ts_changes_unique


def midi_to_key_signature_changes(midi_path):
    """从MIDI文件提取调号变化"""
    mididata = pm.PrettyMIDI(str(midi_path))
    ks_changes = []

    for ks in mididata.key_signature_changes:
        ks_changes.append((ks.time, ks.key_number))

    # 去重
    ks_changes_unique = []
    for i, ks in enumerate(ks_changes):
        if i == 0 or ks[1] != ks_changes[i-1][1]:
            ks_changes_unique.append(ks)

    return ks_changes_unique


def align_ts_to_beats(ts_changes, beat_times, downbeat_times, tolerance=0.0175):
    """将拍号变化对齐到最近的downbeat"""
    aligned_ts = []

    for ts_time, ts_string in ts_changes:
        if ts_time == 0:
            # 第一个拍号，对齐到第一个downbeat
            if downbeat_times:
                aligned_ts.append((downbeat_times[0], ts_string))
            else:
                aligned_ts.append((0, ts_string))
        else:
            # 查找最近的downbeat
            close_dbs = [db for db in downbeat_times
                        if abs(db - ts_time) <= tolerance]
            if close_dbs:
                aligned_ts.append((close_dbs[0], ts_string))
            else:
                # 找不到近的downbeat，使用原始时间
                aligned_ts.append((ts_time, ts_string))

    return aligned_ts


def align_ks_to_beats(ks_changes, beat_times, tolerance=0.0175):
    """将调号变化对齐到最近的beat"""
    aligned_ks = []

    for ks_time, ks_number in ks_changes:
        if ks_time == 0:
            # 第一个调号，对齐到第一个beat
            if beat_times:
                aligned_ks.append((beat_times[0], ks_number))
            else:
                aligned_ks.append((0, ks_number))
        else:
            # 查找最近的beat
            close_beats = [b for b in beat_times
                          if abs(b - ks_time) <= tolerance]
            if close_beats:
                aligned_ks.append((close_beats[0], ks_number))
            else:
                # 找不到近的beat，找右边第一个
                right_beats = [b for b in beat_times if b >= ks_time]
                if right_beats:
                    aligned_ks.append((right_beats[0], ks_number))
                else:
                    aligned_ks.append((ks_time, ks_number))

    return aligned_ks


def generate_score_annotations(midi_score_path, output_path=None):
    """生成MIDI Score的完整annotations"""
    print(f"处理MIDI Score: {midi_score_path}")

    # 1. 提取beat和downbeat
    beats = midi_to_beat_annotations(midi_score_path)
    downbeats = midi_to_downbeat_annotations(midi_score_path)

    # 2. 合并beat和downbeat (downbeat覆盖beat)
    annotations = {**beats, **downbeats}

    # 3. 提取拍号和调号变化
    ts_changes = midi_to_time_signature_changes(midi_score_path)
    ks_changes = midi_to_key_signature_changes(midi_score_path)

    # 4. 对齐拍号和调号到beat/downbeat
    beat_times = sorted(annotations.keys())
    downbeat_times = [t for t, label in annotations.items() if label.startswith('db')]

    aligned_ts = align_ts_to_beats(ts_changes, beat_times, downbeat_times)
    aligned_ks = align_ks_to_beats(ks_changes, beat_times)

    # 5. 构建最终的annotations字典
    final_annotations = {}
    for time, label in sorted(annotations.items()):
        # 基础标签
        final_label = label

        # 添加拍号信息
        ts_at_time = [ts for t, ts in aligned_ts if abs(t - time) < 0.001]
        if ts_at_time:
            final_label += f",{ts_at_time[0]}"
        elif any(abs(t - time) < 0.001 for t, _ in aligned_ks):
            # 有调号但没有拍号，添加空拍号
            final_label += ","

        # 添加调号信息
        ks_at_time = [ks for t, ks in aligned_ks if abs(t - time) < 0.001]
        if ks_at_time:
            if "," not in final_label:
                final_label += ",,"
            final_label += f",{ks_at_time[0]}"

        final_annotations[time] = final_label

    # 6. 保存到文件
    if output_path:
        write_annotations_to_file(final_annotations, output_path)
        print(f"Score annotations已保存到: {output_path}")

    return final_annotations


# ============================================================================
# Part 2: 使用Nakamura对齐算法
# ============================================================================

def run_nakamura_alignment(score_midi, perf_midi, nak_tool_dir):
    """运行Nakamura对齐工具"""
    nak_tool_dir = Path(nak_tool_dir).resolve()
    script_path = nak_tool_dir / "MIDIToMIDIAlign.sh"

    if not script_path.exists():
        raise FileNotFoundError(f"Nakamura对齐脚本不存在: {script_path}")

    # 转换为绝对路径
    score_midi = Path(score_midi).resolve()
    perf_midi = Path(perf_midi).resolve()

    # 获取文件名（不含后缀）
    score_name = score_midi.stem
    perf_name = perf_midi.stem

    # 在MIDI文件所在目录运行
    work_dir = perf_midi.parent

    # 创建一个临时脚本，使用绝对路径
    temp_script = work_dir / "run_alignment_temp.sh"
    programs_dir = nak_tool_dir / "Programs"

    script_content = f"""#!/bin/bash
set -e
PROG="{programs_dir}"
$PROG/midi2pianoroll 0 {score_name}
$PROG/midi2pianoroll 0 {perf_name}
$PROG/SprToFmt3x {score_name}_spr.txt {score_name}_fmt3x.txt
$PROG/Fmt3xToHmm {score_name}_fmt3x.txt {score_name}_hmm.txt
$PROG/ScorePerfmMatcher {score_name}_hmm.txt {perf_name}_spr.txt {perf_name}_pre_match.txt 0.001
$PROG/ErrorDetection {score_name}_fmt3x.txt {score_name}_hmm.txt {perf_name}_pre_match.txt {perf_name}_err_match.txt 0
$PROG/RealignmentMOHMM {score_name}_fmt3x.txt {score_name}_hmm.txt {perf_name}_err_match.txt {perf_name}_realigned_match.txt 0.3
cp {perf_name}_realigned_match.txt {perf_name}_match.txt
$PROG/MatchToCorresp {perf_name}_match.txt {score_name}_spr.txt {perf_name}_corresp.txt
rm {perf_name}_realigned_match.txt {perf_name}_err_match.txt {perf_name}_pre_match.txt {perf_name}_match.txt
"""

    temp_script.write_text(script_content)
    temp_script.chmod(0o755)

    # 运行对齐
    print(f"运行Nakamura对齐: {score_name} -> {perf_name}")
    result = subprocess.run(
        [str(temp_script)],
        cwd=str(work_dir),
        capture_output=True,
        text=True
    )

    # 删除临时脚本
    temp_script.unlink()

    if result.returncode != 0:
        print(f"警告: 对齐过程返回非零状态码: {result.returncode}")
        if result.stderr:
            print(f"错误信息: {result.stderr[:500]}")  # 只显示前500字符

    # 检查输出文件（在work_dir中）
    corresp_file = work_dir / f"{perf_name}_corresp.txt"
    if not corresp_file.exists():
        raise FileNotFoundError(f"对齐结果文件不存在: {corresp_file}")

    return corresp_file


# ============================================================================
# Part 3: 从对齐结果生成Performance Annotations
# ============================================================================

def read_corresp_file(corresp_path):
    """读取Nakamura对齐结果文件"""
    df = pd.read_csv(corresp_path, sep='\t', skiprows=1, header=None)
    df.columns = ["alignID", "alignOntime", "alignSitch", "alignPitch", "alignOnvel",
                  "refID", "refOntime", "refSitch", "refPitch", "refOnvel", "empty"]
    df = df.drop(columns=["empty"])
    # 过滤掉不存在的音符 (alignOntime == -1)
    df = df[df["alignOntime"] != -1]
    return df


def generate_performance_annotations(score_annotations, corresp_df, tolerance=0.020):
    """从score annotations和对齐结果生成performance annotations"""
    # 读取score annotations
    score_ann_list = sorted(score_annotations.items())
    score_times = [t for t, _ in score_ann_list]
    score_labels = [label for _, label in score_ann_list]

    perf_times = []
    missing_list = []

    # 对每个score annotation时间，找到对应的performance时间
    for i, score_time in enumerate(score_times):
        # 在对齐结果中查找±tolerance窗口内的音符
        matched_notes = corresp_df[
            (corresp_df["refOntime"] > score_time - tolerance) &
            (corresp_df["refOntime"] < score_time + tolerance)
        ]

        if len(matched_notes) == 0:
            # 没有匹配的音符
            perf_times.append(None)
            missing_list.append(("missing", score_time))
        else:
            # 使用中位数时间（对抗异常值）
            perf_time = matched_notes["alignOntime"].median()
            perf_times.append(perf_time)

    # 清理时间序列中的异常值（时间倒退）
    for i in range(1, len(perf_times)):
        if (perf_times[i] is not None and
            perf_times[i-1] is not None and
            perf_times[i] < perf_times[i-1]):
            perf_times[i] = None
            missing_list.append(("smaller", perf_times[i]))

    # 插值填充缺失值
    perf_times_series = pd.Series(perf_times)
    perf_times_filled = perf_times_series.interpolate(method='linear').tolist()

    # 填充开头的None值（向前外推）
    first_valid_idx = next((i for i, v in enumerate(perf_times_filled)
                           if not pd.isna(v)), None)
    if first_valid_idx and first_valid_idx > 0:
        for i in range(first_valid_idx - 1, -1, -1):
            if i + 2 < len(perf_times_filled):
                delta = perf_times_filled[i+2] - perf_times_filled[i+1]
                perf_times_filled[i] = max(0, perf_times_filled[i+1] - delta)

    # 构建performance annotations字典
    perf_annotations = {}
    none_indices = [i for i, v in enumerate(perf_times) if v is None]

    for i, (perf_time, label) in enumerate(zip(perf_times_filled, score_labels)):
        # 如果是插值的值，添加警告标记
        if i in none_indices:
            label += "W"
        perf_annotations[perf_time] = label

    return perf_annotations, missing_list


def write_annotations_to_file(annotations, output_path):
    """将annotations写入TSV文件"""
    with open(output_path, 'w') as f:
        for time, label in sorted(annotations.items()):
            f.write(f"{time}\t{time}\t{label}\n")


def read_annotations_from_file(file_path):
    """从文件读取annotations"""
    annotations = {}
    with open(file_path, 'r') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 3:
                time = float(parts[0])
                label = parts[2]
                annotations[time] = label
    return annotations


def compare_annotations(generated_file, reference_file):
    """比较生成的annotations和参考annotations"""
    gen_ann = read_annotations_from_file(generated_file)
    ref_ann = read_annotations_from_file(reference_file)

    print(f"\n比较结果:")
    print(f"  生成的annotations数量: {len(gen_ann)}")
    print(f"  参考的annotations数量: {len(ref_ann)}")

    if len(gen_ann) != len(ref_ann):
        print(f"  ⚠️  数量不一致！")
        return False

    # 比较每个annotation
    gen_times = sorted(gen_ann.keys())
    ref_times = sorted(ref_ann.keys())

    time_diffs = []
    label_diffs = 0

    for i in range(min(len(gen_times), len(ref_times))):
        gen_time = gen_times[i]
        ref_time = ref_times[i]
        gen_label = gen_ann[gen_time].split(',')[0]
        ref_label = ref_ann[ref_time].split(',')[0]

        time_diff = abs(gen_time - ref_time)
        time_diffs.append(time_diff)

        if gen_label != ref_label:
            label_diffs += 1

    if time_diffs:
        avg_time_diff = np.mean(time_diffs)
        max_time_diff = np.max(time_diffs)
        print(f"  平均时间差异: {avg_time_diff:.6f} 秒")
        print(f"  最大时间差异: {max_time_diff:.6f} 秒")
        print(f"  标签差异数量: {label_diffs}")

        if avg_time_diff < 0.001 and label_diffs == 0:
            print(f"  ✓ 完全匹配！")
            return True
        else:
            print(f"  ⚠️  存在差异")
            return False

    return True


# ============================================================================
# Part 4: 单个文件处理
# ============================================================================

def process_single_performance(score_midi, perf_midi, nak_tool_dir,
                               score_ann_output=None, perf_ann_output=None):
    """处理单个performance的完整流程"""
    print(f"\n{'='*60}")
    print(f"处理: {Path(perf_midi).name}")
    print(f"{'='*60}")

    # Step 1: 生成score annotations
    if score_ann_output and not Path(score_ann_output).exists():
        score_annotations = generate_score_annotations(score_midi, score_ann_output)
    else:
        # 如果已存在，直接读取
        if score_ann_output and Path(score_ann_output).exists():
            print(f"Score annotations已存在，跳过生成")
            score_annotations = read_annotations_from_file(score_ann_output)
        else:
            score_annotations = generate_score_annotations(score_midi)

    # Step 2: 运行Nakamura对齐
    corresp_file = run_nakamura_alignment(score_midi, perf_midi, nak_tool_dir)

    # Step 3: 读取对齐结果
    corresp_df = read_corresp_file(corresp_file)
    print(f"对齐结果: {len(corresp_df)} 个音符对应关系")

    # Step 4: 生成performance annotations
    perf_annotations, missing_list = generate_performance_annotations(
        score_annotations, corresp_df
    )

    if missing_list:
        print(f"警告: {len(missing_list)} 个annotations需要插值")

    # Step 5: 保存performance annotations
    if perf_ann_output:
        write_annotations_to_file(perf_annotations, perf_ann_output)
        print(f"Performance annotations已保存到: {perf_ann_output}")

    return perf_annotations, missing_list


# ============================================================================
# Part 5: 批量处理
# ============================================================================

def process_asap_dataset(asap_root, nak_tool_dir, metadata_file=None,
                         regenerate_score=False, compare_results=True, limit=None):
    """批量处理ASAP数据集"""
    asap_root = Path(asap_root)

    # 读取metadata
    if metadata_file is None:
        metadata_file = asap_root / "metadata.csv"

    print(f"读取metadata: {metadata_file}")
    df = pd.read_csv(metadata_file)

    if limit:
        df = df.head(limit)
        print(f"限制处理前 {limit} 个performance")

    print(f"找到 {len(df)} 个performance")

    # 统计信息
    total = len(df)
    success = 0
    failed = 0
    perfect_match = 0
    time_match = 0
    results = []

    # 处理每个performance
    for idx, row in df.iterrows():
        try:
            print(f"\n[{idx+1}/{total}] 处理: {row['midi_performance']}")

            score_midi = asap_root / row['midi_score']
            perf_midi = asap_root / row['midi_performance']
            score_ann_output = asap_root / row['midi_score_annotations']
            perf_ann_output = asap_root / row['performance_annotations']

            # 如果不重新生成score annotations，且文件已存在，则跳过
            if not regenerate_score and score_ann_output.exists():
                score_ann_output = None

            # 生成annotations
            perf_annotations, missing_list = process_single_performance(
                str(score_midi),
                str(perf_midi),
                nak_tool_dir,
                str(score_ann_output) if score_ann_output else None,
                str(perf_ann_output) + ".new"  # 先生成到.new文件
            )

            # 对比结果
            if compare_results:
                original_ann = asap_root / row['performance_annotations']
                if original_ann.exists():
                    match_result = compare_annotations(
                        str(perf_ann_output) + ".new",
                        str(original_ann)
                    )

                    # 记录结果
                    result_info = {
                        'performance': row['midi_performance'],
                        'success': True,
                        'perfect_match': match_result,
                        'num_annotations': len(perf_annotations),
                        'num_missing': len(missing_list)
                    }
                    results.append(result_info)

                    if match_result:
                        perfect_match += 1
                        print("  ✓ 完全匹配！")
                    else:
                        time_match += 1
                        print("  ⚠️  时间匹配但标签有差异")

            success += 1

        except Exception as e:
            print(f"❌ 失败: {e}")
            import traceback
            traceback.print_exc()

            result_info = {
                'performance': row['midi_performance'],
                'success': False,
                'error': str(e)
            }
            results.append(result_info)
            failed += 1
            continue

    # 保存结果统计
    results_df = pd.DataFrame(results)
    results_file = asap_root / "annotation_generation_results.csv"
    results_df.to_csv(results_file, index=False)
    print(f"\n结果已保存到: {results_file}")

    # 打印统计
    print(f"\n{'='*60}")
    print(f"处理完成！")
    print(f"  总数: {total}")
    print(f"  成功: {success}")
    print(f"  失败: {failed}")
    if compare_results:
        print(f"  完全匹配: {perfect_match}")
        print(f"  时间匹配: {time_match}")
        print(f"  匹配率: {perfect_match/total*100:.1f}%")
    print(f"{'='*60}")

    return results_df


# ============================================================================
# Part 6: 主程序
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='ASAP数据集annotation生成工具（支持单个文件和批量处理）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:

  # 批量处理整个数据集（默认模式）
  python generate_asap_annotations.py \\
    --asap-root data/asap-dataset \\
    --nak-tool-dir data/asap-dataset/util/nak_alignment

  # 只处理前10个（测试）
  python generate_asap_annotations.py \\
    --asap-root data/asap-dataset \\
    --nak-tool-dir data/asap-dataset/util/nak_alignment \\
    --limit 10

  # 处理单个文件
  python generate_asap_annotations.py \\
    --score-midi data/asap-dataset/Chopin/Etudes_op_25/1/midi_score.mid \\
    --perf-midi data/asap-dataset/Chopin/Etudes_op_25/1/Erice03.mid \\
    --nak-tool-dir data/asap-dataset/util/nak_alignment \\
    --perf-output output.txt
        """
    )

    # 批量处理参数
    parser.add_argument('--asap-root',
                       help='ASAP数据集根目录（批量处理模式）')
    parser.add_argument('--metadata',
                       help='metadata.csv文件路径（默认为asap-root/metadata.csv）')
    parser.add_argument('--limit', type=int,
                       help='只处理前N个performance（用于测试）')
    parser.add_argument('--regenerate-score', action='store_true',
                       help='重新生成score annotations')
    parser.add_argument('--no-compare', action='store_true',
                       help='不对比生成结果与原始数据')

    # 单个文件处理参数
    parser.add_argument('--score-midi',
                       help='MIDI score文件路径（单文件模式）')
    parser.add_argument('--perf-midi',
                       help='MIDI performance文件路径（单文件模式）')
    parser.add_argument('--score-output',
                       help='Score annotations输出路径')
    parser.add_argument('--perf-output',
                       help='Performance annotations输出路径')
    parser.add_argument('--compare-with',
                       help='参考annotations文件路径（用于对比）')

    # 共同参数
    parser.add_argument('--nak-tool-dir', required=True,
                       help='Nakamura对齐工具目录')

    args = parser.parse_args()

    # 判断是批量处理还是单文件处理
    if args.asap_root:
        # 批量处理模式
        print("=" * 60)
        print("批量处理模式")
        print("=" * 60)
        results = process_asap_dataset(
            args.asap_root,
            args.nak_tool_dir,
            args.metadata,
            args.regenerate_score,
            not args.no_compare,
            args.limit
        )
        print(f"\n详细结果已保存到: {args.asap_root}/annotation_generation_results.csv")

    elif args.score_midi and args.perf_midi:
        # 单文件处理模式
        print("=" * 60)
        print("单文件处理模式")
        print("=" * 60)
        perf_annotations, missing_list = process_single_performance(
            args.score_midi,
            args.perf_midi,
            args.nak_tool_dir,
            args.score_output,
            args.perf_output
        )

        # 如果提供了参考文件，进行对比
        if args.compare_with and args.perf_output:
            print(f"\n{'='*60}")
            print("对比生成结果与参考文件")
            print(f"{'='*60}")
            compare_annotations(args.perf_output, args.compare_with)

        print(f"\n✓ 处理完成！")
        print(f"  生成了 {len(perf_annotations)} 个performance annotations")
        if missing_list:
            print(f"  其中 {len(missing_list)} 个需要插值")

    else:
        parser.error("必须指定 --asap-root（批量处理）或 --score-midi 和 --perf-midi（单文件处理）")


if __name__ == '__main__':
    main()
