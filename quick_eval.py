#!/usr/bin/env python3
"""快速评估脚本"""
import subprocess

def parse_alignment(s):
    alignments = {}
    for pair in s.strip().split():
        if ':' in pair:
            parts = pair.split(':')
            if len(parts) == 2 and parts[0] and parts[1]:
                alignments[int(parts[0])] = int(parts[1])
    return alignments

# Ground truth
gt_str = "1:91 2:689 3:1238 4:1602 5:2239 6:2724 7:3197 8:3528 9:4173 10:4679 11:5169 12:5505 13:6110 14:6532 15:6937 16:7340 17:7747 18:8145 19:8530 20:8929 21:9342 22:9741 23:10096 24:10452 25:10817 26:11184 27:11560 28:11924 29:12278 30:12678 31:13099 32:13487 33:14027 34:14895 35:15386 36:16750 37:17131 38:17503 39:17852 40:18199 41:18543 42:18902 43:19243 44:19591 45:19907 46:20220 47:20521 48:20824 49:21160 50:21500 51:21817 52:22142 53:22528 54:22871 55:23209 56:23623 57:23872 58:24058 59:24758 60:25672 61:26180 62:26591 63:26926 64:27255 65:27750 66:28128 67:28394 68:28682 69:28971 70:29197 71:29778 72:30336 73:30792 74:31302 75:31847 76:32481"
gt = parse_alignment(gt_str)

# 运行global_dp算法
result = subprocess.run(['python3', 'align_measures_global_dp.py',
                        'data/abc_from_xml/Glinka/The_Lark/Glinka_The_Lark.abcx',
                        'data/asap-dataset/Glinka/The_Lark/Denisova10M.mid'],
                       capture_output=True, text=True, check=True)
pred = parse_alignment(result.stdout)

# 评估不同tolerance
for tol in [0, 1, 5, 10, 50, 100]:
    correct = sum(1 for m, gt_tick in gt.items()
                  if m in pred and abs(pred[m] - gt_tick) <= tol)
    acc = correct / len(gt) * 100
    print(f"Tolerance {tol:3d}: {acc:5.1f}% ({correct}/{len(gt)})")
