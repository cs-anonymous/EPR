#!/usr/bin/env python3
"""
直接从MIDI文件提取音符事件的时间戳。
"""

import argparse
import mido


def midi_to_events(midi_path):
    """从MIDI文件提取所有音符事件及其时间戳。

    Returns:
        List of (time_seconds, pitch, velocity) tuples
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

    return events


def main():
    parser = argparse.ArgumentParser(description='从MIDI提取音符事件时间戳')
    parser.add_argument('midi_file', help='MIDI文件路径')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')

    args = parser.parse_args()

    events = midi_to_events(args.midi_file)

    if args.verbose:
        print(f"找到 {len(events)} 个音符事件")
        print("\n前10个事件:")
        for i, (time, pitch, vel) in enumerate(events[:10], 1):
            print(f"{i}: {time:.3f}s, pitch={pitch}, vel={vel}")

        print("\n后10个事件:")
        for i, (time, pitch, vel) in enumerate(events[-10:], len(events)-9):
            print(f"{i}: {time:.3f}s, pitch={pitch}, vel={vel}")
    else:
        for i, (time, pitch, vel) in enumerate(events, 1):
            print(f"{i}\t{time:.6f}\t{pitch}\t{vel}")


if __name__ == '__main__':
    main()
