#!/usr/bin/env python3
"""
测试处理流程（不需要 alignment）
验证：
1. MusicXML → ABCX 转换
2. MIDI 读取
3. Score measure 提取
"""

import sys
from pathlib import Path
import music21
import pretty_midi

sys.path.insert(0, str(Path(__file__).parent.parent))
from xml_to_abcx import xml_to_abcx


def test_xml_to_abcx():
    """测试 MusicXML → ABCX"""
    xml_file = "/home/sy/EPR/PianoCoRe/PianoCoRe/raw/Abreu,_Zequinha/Tico-Tico_no_fubá/score.mxl"
    
    print("=" * 60)
    print("测试 1: MusicXML → ABCX")
    print("=" * 60)
    
    try:
        abcx = xml_to_abcx(xml_file)
        print(f"✓ 转换成功")
        print(f"ABCX 长度: {len(abcx)} 字符")
        print(f"\n前 500 字符:")
        print(abcx[:500])
        return True
    except Exception as e:
        print(f"✗ 转换失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_midi_loading():
    """测试 MIDI 加载"""
    midi_file = "/home/sy/EPR/PianoCoRe/PianoCoRe/raw/Abreu,_Zequinha/Tico-Tico_no_fubá/Aria_104059_0.mid"
    
    print("\n" + "=" * 60)
    print("测试 2: MIDI 加载")
    print("=" * 60)
    
    try:
        midi = pretty_midi.PrettyMIDI(midi_file)
        print(f"✓ 加载成功")
        print(f"乐器数量: {len(midi.instruments)}")
        
        for i, inst in enumerate(midi.instruments):
            print(f"  乐器 {i}: {inst.program}, 音符数: {len(inst.notes)}")
        
        return True
    except Exception as e:
        print(f"✗ 加载失败: {e}")
        return False


def test_score_measures():
    """测试 Score measure 提取"""
    xml_file = "/home/sy/EPR/PianoCoRe/PianoCoRe/raw/Abreu,_Zequinha/Tico-Tico_no_fubá/score.mxl"
    
    print("\n" + "=" * 60)
    print("测试 3: Score Measure 提取")
    print("=" * 60)
    
    try:
        score = music21.converter.parse(xml_file)
        print(f"✓ Score 加载成功")
        print(f"Parts 数量: {len(score.parts)}")
        
        measures = []
        for part_idx, part in enumerate(score.parts):
            part_measures = list(part.getElementsByClass('Measure'))
            print(f"  Part {part_idx}: {len(part_measures)} 小节")
            
            for measure in part_measures[:3]:  # 只显示前 3 个
                notes = list(measure.flatten().notes)
                print(f"    小节 {measure.number}: offset={measure.offset}, "
                      f"duration={measure.duration.quarterLength}, "
                      f"notes={len(notes)}")
            
            measures.extend(part_measures)
        
        print(f"\n总小节数: {len(measures)}")
        return True
        
    except Exception as e:
        print(f"✗ 提取失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("PianoCoRe 处理流程测试")
    print("=" * 60)
    
    results = []
    results.append(("MusicXML → ABCX", test_xml_to_abcx()))
    results.append(("MIDI 加载", test_midi_loading()))
    results.append(("Score Measure 提取", test_score_measures()))
    
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    for name, success in results:
        status = "✓ 通过" if success else "✗ 失败"
        print(f"{name}: {status}")
    
    all_passed = all(r[1] for r in results)
    print("\n" + ("=" * 60))
    if all_passed:
        print("✓ 所有测试通过！")
        print("等待 alignment 和 refined 数据下载完成后，即可运行完整处理流程。")
    else:
        print("✗ 部分测试失败，请检查错误信息。")
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
