#!/usr/bin/env python3
"""
从MIDI score生成ASAP格式的annotations

ASAP的annotations是从MIDI score中提取的，而不是从MusicXML直接计算的。
这个脚本使用music21解析MIDI文件，提取实际的beat时间。
"""

import music21 as m21
import pandas as pd
from pathlib import Path
import argparse


def ts2n_of_beats(ts_string):
    """根据拍号字符串获取每小节的拍数"""
    num = int(ts_string.split("/")[0])
    if num == 1:
        return 1
    elif num == 2 or num == 6:
        return 2
    elif num == 3 or num == 9:
        return 3
    elif num == 4 or num == 12:
        return 4
    elif num == 5:
        return 5
    elif num == 24:
        return 8
    else:
        # 对于非标准拍号，返回None表示这是一个rubato小节
        return None


def is_rubato_measure(ts):
    """判断是否是rubato小节（非标准拍号）"""
    if ts is None:
        return False
    # 非标准拍号通常表示rubato
    standard_numerators = [1, 2, 3, 4, 5, 6, 9, 12, 24]
    return ts.numerator not in standard_numerators


def get_key_signature_number(key_sig):
    """从KeySignature对象获取升降号数量"""
    return key_sig.sharps


def generate_annotations_from_midi(midi_path, xml_path=None, output_path=None):
    """
    从MIDI score生成ASAP格式的annotations

    参数:
        midi_path: MIDI文件路径
        xml_path: 可选的MusicXML文件路径（用于获取更准确的拍号/调号信息）
        output_path: 输出的annotation文件路径

    返回:
        annotations列表
    """
    print(f"解析MIDI文件: {midi_path}")
    score = m21.converter.parse(midi_path)

    # 如果提供了XML文件，也解析它以获取更准确的信息
    xml_score = None
    if xml_path:
        print(f"解析MusicXML文件: {xml_path}")
        xml_score = m21.converter.parse(xml_path)

    # 获取第一个part
    if len(score.parts) == 0:
        raise ValueError("MIDI文件中没有找到任何part")

    part = score.parts[0]

    # 获取所有小节
    measures = part.recurse().getElementsByClass(m21.stream.Measure)

    annotations = []

    # 获取初始拍号和调号
    current_ts = None
    current_ks = None

    for measure_idx, measure in enumerate(measures):
        # 获取小节的拍号
        ts_list = measure.getElementsByClass(m21.meter.TimeSignature)
        if ts_list:
            current_ts = ts_list[0]
        elif measure_idx == 0:
            # 默认4/4
            current_ts = m21.meter.TimeSignature('4/4')

        # 检查是否是rubato小节
        is_rubato = is_rubato_measure(current_ts)

        if is_rubato:
            # Rubato小节：使用实际的quarterLength来估算拍数
            # 或者标记所有beat为bR
            ts_string = f"{current_ts.numerator}/{current_ts.denominator}"
            # 对于rubato，我们仍然需要估算拍数
            # 使用quarterLength除以标准拍的长度
            estimated_beats = int(measure.quarterLength / (4.0 / current_ts.denominator))
            n_beats = max(1, estimated_beats)
        else:
            ts_string = f"{current_ts.numerator}/{current_ts.denominator}"
            n_beats = ts2n_of_beats(ts_string)
            if n_beats is None:
                # 如果无法确定拍数，使用quarterLength估算
                n_beats = max(1, int(measure.quarterLength))

        # 获取小节的调号
        ks_list = measure.getElementsByClass(m21.key.KeySignature)
        if ks_list:
            current_ks = ks_list[0]
        elif measure_idx == 0:
            current_ks = m21.key.KeySignature(0)

        ks_number = get_key_signature_number(current_ks)

        # 获取小节的开始时间（秒）
        # 使用music21的seconds属性，它会根据tempo计算实际时间
        try:
            measure_start_seconds = measure.seconds
        except:
            # 如果无法获取seconds，使用offset和tempo计算
            measure_start_seconds = measure.offset * 0.5  # 假设120 BPM

        # 获取小节的时长（秒）
        measure_duration_quarters = measure.quarterLength
        # 计算小节的实际时长（秒）
        # 需要考虑tempo变化
        tempo_list = measure.getElementsByClass(m21.tempo.MetronomeMark)
        if tempo_list:
            current_tempo = tempo_list[0].number
        elif measure_idx == 0:
            # 查找全局tempo
            all_tempos = part.flatten().getElementsByClass(m21.tempo.MetronomeMark)
            if all_tempos:
                current_tempo = all_tempos[0].number
            else:
                current_tempo = 120  # 默认120 BPM

        # 计算小节时长（秒）
        seconds_per_quarter = 60.0 / current_tempo
        measure_duration_seconds = measure_duration_quarters * seconds_per_quarter

        # 计算每拍的时长
        beat_duration_seconds = measure_duration_seconds / n_beats

        # 添加downbeat annotation
        if is_rubato:
            label = "bR"  # rubato小节的第一拍也标记为bR
        else:
            label = "db"

        if measure_idx == 0 and not is_rubato:
            # 第一个小节添加拍号和调号信息
            label = f"db,{ts_string},{ks_number}"
        elif ts_list and not is_rubato:
            # 拍号变化
            label = f"db,{ts_string}"
        elif ks_list and not is_rubato:
            # 调号变化
            label = f"db,,{ks_number}"

        annotations.append((measure_start_seconds, measure_start_seconds, label))

        # 添加其他拍的annotations
        for beat_idx in range(1, n_beats):
            beat_time = measure_start_seconds + beat_idx * beat_duration_seconds
            beat_label = "bR" if is_rubato else "b"
            annotations.append((beat_time, beat_time, beat_label))

    print(f"生成了 {len(annotations)} 个annotations，共 {len(measures)} 个小节")

    # 保存到文件
    if output_path:
        with open(output_path, 'w') as f:
            for ann in annotations:
                f.write(f"{ann[0]:.6f}\t{ann[1]:.6f}\t{ann[2]}\n")
        print(f"Annotations已保存到: {output_path}")

    return annotations


def compare_annotations(generated_file, reference_file):
    """比较生成的annotations和参考annotations"""
    print(f"\n比较annotations:")
    print(f"  生成文件: {generated_file}")
    print(f"  参考文件: {reference_file}")

    # 读取两个文件
    gen_df = pd.read_csv(generated_file, sep='\t', header=None,
                         names=['onset', 'offset', 'label'], dtype={'label': str})
    ref_df = pd.read_csv(reference_file, sep='\t', header=None,
                         names=['onset', 'offset', 'label'], dtype={'label': str})

    # 移除空行
    gen_df = gen_df.dropna(subset=['label'])
    ref_df = ref_df.dropna(subset=['label'])

    print(f"\n生成的annotations数量: {len(gen_df)}")
    print(f"参考的annotations数量: {len(ref_df)}")

    if len(gen_df) != len(ref_df):
        print(f"⚠️  数量不一致！差异: {abs(len(gen_df) - len(ref_df))}")

    # 比较每一行
    differences = []
    min_len = min(len(gen_df), len(ref_df))

    for i in range(min_len):
        gen_row = gen_df.iloc[i]
        ref_row = ref_df.iloc[i]

        # 比较label
        gen_label = gen_row['label'].split(',')[0]
        ref_label = ref_row['label'].split(',')[0]

        if gen_label != ref_label:
            differences.append({
                'index': i,
                'gen_label': gen_label,
                'ref_label': ref_label,
                'gen_time': gen_row['onset'],
                'ref_time': ref_row['onset']
            })

    print(f"\n标签匹配数量: {min_len - len(differences)}/{min_len}")

    if differences:
        print(f"\n发现 {len(differences)} 处差异:")
        for diff in differences[:10]:
            print(f"  索引 {diff['index']}: 生成={diff['gen_label']}, 参考={diff['ref_label']}, 时间差={abs(diff['gen_time']-diff['ref_time']):.3f}s")
    else:
        print("✓ 所有标签完全匹配！")

    # 比较时间
    time_diffs = []
    for i in range(min_len):
        gen_row = gen_df.iloc[i]
        ref_row = ref_df.iloc[i]

        gen_label = gen_row['label'].split(',')[0]
        ref_label = ref_row['label'].split(',')[0]

        if gen_label == ref_label:
            time_diff = abs(gen_row['onset'] - ref_row['onset'])
            time_diffs.append(time_diff)

    if time_diffs:
        avg_time_diff = sum(time_diffs) / len(time_diffs)
        max_time_diff = max(time_diffs)
        print(f"\n时间差异统计（相同标签）:")
        print(f"  平均差异: {avg_time_diff:.6f} 秒")
        print(f"  最大差异: {max_time_diff:.6f} 秒")

        # 统计小于某些阈值的比例
        thresholds = [0.001, 0.01, 0.1, 1.0]
        for threshold in thresholds:
            count = sum(1 for d in time_diffs if d < threshold)
            percentage = count / len(time_diffs) * 100
            print(f"  < {threshold}s: {count}/{len(time_diffs)} ({percentage:.1f}%)")

    return len(differences), min_len, differences


def main():
    parser = argparse.ArgumentParser(
        description='从MIDI score生成ASAP格式的annotations并与参考文件对比'
    )
    parser.add_argument('midi_file', help='MIDI文件路径')
    parser.add_argument('--xml', '-x', help='可选的MusicXML文件路径')
    parser.add_argument('--reference', '-r', help='参考annotation文件路径')
    parser.add_argument('--output', '-o', help='输出annotation文件路径')

    args = parser.parse_args()

    # 生成annotations
    midi_path = Path(args.midi_file)
    if not midi_path.exists():
        print(f"错误: 文件不存在: {midi_path}")
        return

    output_path = args.output
    if not output_path:
        output_path = midi_path.parent / f"{midi_path.stem}_generated_annotations.txt"

    xml_path = args.xml if args.xml else None

    annotations = generate_annotations_from_midi(
        midi_path,
        xml_path=xml_path,
        output_path=output_path
    )

    # 如果提供了参考文件，进行对比
    if args.reference:
        ref_path = Path(args.reference)
        if ref_path.exists():
            compare_annotations(output_path, ref_path)
        else:
            print(f"警告: 参考文件不存在: {ref_path}")


if __name__ == '__main__':
    main()
