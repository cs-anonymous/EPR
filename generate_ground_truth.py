#!/usr/bin/env python3
"""
从ASAP的annotations.txt生成小节对齐的标准答案。

输入：
- annotations.txt: ASAP的音符级对齐标注
- MIDI文件

输出：
- 小节号到事件索引的映射
"""

import argparse
import mido
from pathlib import Path


def parse_annotations(annotations_path):
    """解析annotations.txt，提取所有downbeat的时间戳。"""
    downbeats = []
    with open(annotations_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) >= 3 and 'db' in parts[2]:
                # 格式: 时间戳 时间戳 db[,...]
                timestamp = float(parts[0])
                downbeats.append(timestamp)
    return downbeats


def midi_to_events(midi_path):
    """从MIDI文件提取所有音符事件及其时间戳。

    Returns:
        List of (event_index, time_seconds, pitch, velocity) tuples
    """
    mid = mido.MidiFile(midi_path)
    events = []

    # 处理每个音轨
    for track in mid.tracks:
        current_time = 0  # 累积时间（ticks）
        tempo = 500000  # 默认tempo (120 BPM)

        for msg in track:
            current_time += msg.time

            # 更新tempo
            if msg.type == 'set_tempo':
                tempo = msg.tempo

            # 记录note_on事件
            elif msg.type == 'note_on' and msg.velocity > 0:
                # 转换为秒
                time_seconds = mido.tick2second(
                    current_time,
                    mid.ticks_per_beat,
                    tempo
                )
                events.append((time_seconds, msg.note, msg.velocity))

    # 按时间排序
    events.sort(key=lambda x: x[0])

    # 添加索引
    indexed_events = [(i+1, time, pitch, vel) for i, (time, pitch, vel) in enumerate(events)]

    return indexed_events


def find_closest_event(timestamp, events):
    """找到最接近给定时间戳的音符事件。

    Args:
        timestamp: 目标时间戳（秒）
        events: [(event_index, time_seconds, pitch, velocity), ...]

    Returns:
        (event_index, time_diff)
    """
    min_diff = float('inf')
    best_index = None

    for event_idx, event_time, pitch, vel in events:
        diff = abs(event_time - timestamp)

        if diff < min_diff:
            min_diff = diff
            best_index = event_idx

    return best_index, min_diff


def generate_ground_truth(annotations_path, midi_path, verbose=False):
    """生成小节对齐的标准答案。

    输出格式：小节号 -> tick值（时间戳秒数 * 100，10ms = 1 tick）
    """
    # 解析annotations
    if verbose:
        print(f"解析 annotations: {annotations_path}")
    downbeats = parse_annotations(annotations_path)
    if verbose:
        print(f"找到 {len(downbeats)} 个小节标记")

    # 解析MIDI
    if verbose:
        print(f"解析 MIDI: {midi_path}")
    events = midi_to_events(midi_path)
    if verbose:
        print(f"找到 {len(events)} 个音符事件")

    # 为每个downbeat找到最接近的事件，并转换为tick
    alignments = {}
    for measure_num, timestamp in enumerate(downbeats, 1):
        event_idx, diff = find_closest_event(timestamp, events)

        # 找到该事件的时间戳
        event_time = events[event_idx - 1][1]  # event_idx是1-based

        # 转换为tick（10ms = 1 tick）
        tick = int(event_time * 100)

        alignments[measure_num] = tick

        if verbose:
            print(f"小节 {measure_num}: 时间 {timestamp:.3f}s -> tick {tick} (事件 {event_idx}, 误差 {diff:.3f}s)")

    return alignments


def main():
    parser = argparse.ArgumentParser(description='从ASAP annotations生成小节对齐标准答案')
    parser.add_argument('annotations_file', help='ASAP annotations.txt文件路径')
    parser.add_argument('midi_file', help='MIDI文件路径')
    parser.add_argument('--output', '-o', help='输出文件路径（可选）')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')

    args = parser.parse_args()

    # 生成标准答案
    alignments = generate_ground_truth(args.annotations_file, args.midi_file, args.verbose)

    # 输出结果
    result = ' '.join(f"{m}:{idx}" for m, idx in sorted(alignments.items()))
    print(result)

    # 保存到文件
    if args.output:
        with open(args.output, 'w') as f:
            f.write(result + '\n')
        if args.verbose:
            print(f"\n结果已保存到: {args.output}")


if __name__ == '__main__':
    main()
