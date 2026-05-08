#!/usr/bin/env python3
"""
复现ASAP数据集的annotation生成算法

根据ASAP数据集的文档和代码，annotations是从MusicXML乐谱中提取的：
1. 使用music21解析MusicXML文件
2. 提取每个小节的beat和downbeat位置
3. 处理拍号变化和调号变化
4. 处理特殊情况（pickup measure, rubato等）
"""

import music21 as m21
import pandas as pd
from pathlib import Path
import argparse


def ts2n_of_beats(ts_string):
    """
    根据拍号字符串获取每小节的拍数

    参考ASAP的规则：
    - 2/4, 6/8 -> 2拍
    - 3/4, 9/8 -> 3拍
    - 4/4, 12/8 -> 4拍
    """
    num = int(ts_string.split("/")[0])
    if num == 1:
        return 1
    elif num == 2 or num == 6:  # duple meter
        return 2
    elif num == 3 or num == 9:  # triple meter
        return 3
    elif num == 4 or num == 12:  # quadruple meter
        return 4
    elif num == 5:
        return 5
    elif num == 24:
        return 8
    else:
        raise ValueError(f"Unsupported time signature: {ts_string}")


def get_key_signature_number(key_sig):
    """
    从music21的KeySignature对象获取升降号数量
    正数表示升号，负数表示降号
    """
    return key_sig.sharps


def generate_annotations_from_musicxml(xml_path, output_path=None, tempo_bpm=120):
    """
    从MusicXML文件生成ASAP格式的annotations

    参数:
        xml_path: MusicXML文件路径
        output_path: 输出的annotation文件路径（如果为None则不保存）
        tempo_bpm: 默认速度（BPM），用于计算时间

    返回:
        annotations列表，每个元素是(measure_num, onset_time, offset_time, label)
    """
    print(f"解析MusicXML文件: {xml_path}")
    score = m21.converter.parse(xml_path)

    # 获取第一个part（通常是右手）
    if len(score.parts) == 0:
        raise ValueError("MusicXML文件中没有找到任何part")

    part = score.parts[0]

    # 获取所有小节
    measures = part.recurse().getElementsByClass(m21.stream.Measure)

    annotations = []
    measure_number = 1
    current_time = 0.0

    # 获取初始拍号和调号
    initial_ts = None
    initial_ks = None

    # 检查是否有pickup measure
    has_pickup = False
    if len(measures) > 0:
        first_measure = measures[0]
        if first_measure.paddingLeft > 0:
            has_pickup = True
            print(f"检测到pickup measure，paddingLeft={first_measure.paddingLeft}")

    for measure_idx, measure in enumerate(measures):
        # 获取小节的拍号
        ts_list = measure.getElementsByClass(m21.meter.TimeSignature)
        if ts_list:
            current_ts = ts_list[0]
            ts_string = f"{current_ts.numerator}/{current_ts.denominator}"
            n_beats = ts2n_of_beats(ts_string)
        elif measure_idx == 0:
            # 如果第一个小节没有拍号，使用默认4/4
            current_ts = m21.meter.TimeSignature('4/4')
            ts_string = "4/4"
            n_beats = 4
        else:
            # 使用之前的拍号
            ts_string = f"{current_ts.numerator}/{current_ts.denominator}"
            n_beats = ts2n_of_beats(ts_string)

        # 获取小节的调号
        ks_list = measure.getElementsByClass(m21.key.KeySignature)
        if ks_list:
            current_ks = ks_list[0]
            ks_number = get_key_signature_number(current_ks)
        elif measure_idx == 0:
            # 如果第一个小节没有调号，默认为C大调（0个升降号）
            current_ks = m21.key.KeySignature(0)
            ks_number = 0
        else:
            ks_number = get_key_signature_number(current_ks)

        # 保存初始拍号和调号
        if measure_idx == 0:
            initial_ts = ts_string
            initial_ks = ks_number

        # 计算小节的时长（秒）
        quarter_length = measure.quarterLength
        # 使用固定速度计算时间（实际ASAP使用MIDI的tempo）
        seconds_per_quarter = 60.0 / tempo_bpm
        measure_duration = quarter_length * seconds_per_quarter

        # 计算每拍的时长
        beat_duration = measure_duration / n_beats

        # 添加downbeat annotation
        label = "db"
        if measure_idx == 0:
            # 第一个小节添加拍号和调号信息
            label = f"db,{ts_string},{ks_number}"
        elif ts_list:
            # 拍号变化
            label = f"db,{ts_string}"
        elif ks_list:
            # 调号变化
            label = f"db,,{ks_number}"

        annotations.append((measure_number, current_time, current_time, label))

        # 添加其他拍的annotations
        for beat_idx in range(1, n_beats):
            beat_time = current_time + beat_idx * beat_duration
            annotations.append((measure_number, beat_time, beat_time, "b"))

        # 更新时间和小节号
        current_time += measure_duration
        measure_number += 1

    print(f"生成了 {len(annotations)} 个annotations，共 {measure_number-1} 个小节")

    # 保存到文件
    if output_path:
        with open(output_path, 'w') as f:
            for ann in annotations:
                # ASAP格式：onset \t offset \t label（不包含measure number）
                f.write(f"{ann[1]:.6f}\t{ann[2]:.6f}\t{ann[3]}\n")
        print(f"Annotations已保存到: {output_path}")

    return annotations


def compare_annotations(generated_file, reference_file):
    """
    比较生成的annotations和参考annotations

    返回:
        (相同数量, 总数量, 差异列表)
    """
    print(f"\n比较annotations:")
    print(f"  生成文件: {generated_file}")
    print(f"  参考文件: {reference_file}")

    # 读取两个文件（ASAP格式：onset, offset, label）
    gen_df = pd.read_csv(generated_file, sep='\t', header=None,
                         names=['onset', 'offset', 'label'], dtype={'label': str})
    ref_df = pd.read_csv(reference_file, sep='\t', header=None,
                         names=['onset', 'offset', 'label'], dtype={'label': str})

    # 移除空行（label为NaN的行）
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

        # 比较label（去掉时间信息）
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
        for diff in differences[:10]:  # 只显示前10个差异
            print(f"  索引 {diff['index']}: 生成={diff['gen_label']}, 参考={diff['ref_label']}, 时间差={abs(diff['gen_time']-diff['ref_time']):.3f}s")
    else:
        print("✓ 所有标签完全匹配！")

    # 比较时间（只比较相同标签的）
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
        print(f"\n时间差异统计:")
        print(f"  平均差异: {avg_time_diff:.6f} 秒")
        print(f"  最大差异: {max_time_diff:.6f} 秒")

    return len(differences), min_len, differences


def main():
    parser = argparse.ArgumentParser(
        description='从MusicXML生成ASAP格式的annotations并与参考文件对比'
    )
    parser.add_argument('xml_file', help='MusicXML文件路径')
    parser.add_argument('--reference', '-r', help='参考annotation文件路径')
    parser.add_argument('--output', '-o', help='输出annotation文件路径')
    parser.add_argument('--tempo', '-t', type=float, default=120,
                       help='默认速度（BPM），默认120')

    args = parser.parse_args()

    # 生成annotations
    xml_path = Path(args.xml_file)
    if not xml_path.exists():
        print(f"错误: 文件不存在: {xml_path}")
        return

    output_path = args.output
    if not output_path:
        output_path = xml_path.parent / f"{xml_path.stem}_generated_annotations.txt"

    annotations = generate_annotations_from_musicxml(
        xml_path,
        output_path,
        tempo_bpm=args.tempo
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
