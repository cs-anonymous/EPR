#!/usr/bin/env python3
"""
Compare S3 vs Astar final models
"""

import matplotlib.pyplot as plt
import numpy as np

# Data from analysis
rounds = ['S1', 'S2', 'S3', 'A*1', 'A*2', 'A*3']
final_loss = [1.3629, 1.2717, 1.2651, 1.2741, 1.2690, 1.2502]
min_loss = [1.3178, 1.2630, 1.2404, 1.2379, 1.2305, 1.2157]

# Create figure with two subplots
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

# Left: Bar chart comparison
x = np.arange(len(rounds))
width = 0.35

bars1 = ax1.bar(x - width/2, final_loss, width, label='最终 Loss', alpha=0.8, color='#2E86AB')
bars2 = ax1.bar(x + width/2, min_loss, width, label='最低 Loss', alpha=0.8, color='#F18F01')

# Add S3 reference lines
ax1.axhline(y=1.2651, color='red', linestyle='--', linewidth=1.5, alpha=0.6, label='S3 最终 Loss')
ax1.axhline(y=1.2404, color='orange', linestyle='--', linewidth=1.5, alpha=0.6, label='S3 最低 Loss')

ax1.set_xlabel('训练轮次', fontsize=12, weight='bold')
ax1.set_ylabel('Loss', fontsize=12, weight='bold')
ax1.set_title('各轮次 Loss 对比', fontsize=14, weight='bold', pad=15)
ax1.set_xticks(x)
ax1.set_xticklabels(rounds)
ax1.legend(fontsize=10)
ax1.grid(True, alpha=0.3, linestyle=':', axis='y')

# Add value labels on bars
for bars in [bars1, bars2]:
    for bar in bars:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.4f}', ha='center', va='bottom', fontsize=8)

# Right: Relative to S3
s3_final = 1.2651
s3_min = 1.2404

relative_final = [(loss - s3_final) / s3_final * 100 for loss in final_loss]
relative_min = [(loss - s3_min) / s3_min * 100 for loss in min_loss]

bars3 = ax2.bar(x - width/2, relative_final, width, label='相对 S3 最终', alpha=0.8, color='#2E86AB')
bars4 = ax2.bar(x + width/2, relative_min, width, label='相对 S3 最低', alpha=0.8, color='#F18F01')

ax2.axhline(y=0, color='black', linestyle='-', linewidth=1)
ax2.set_xlabel('训练轮次', fontsize=12, weight='bold')
ax2.set_ylabel('相对 S3 的变化 (%)', fontsize=12, weight='bold')
ax2.set_title('相对 S3 的改进', fontsize=14, weight='bold', pad=15)
ax2.set_xticks(x)
ax2.set_xticklabels(rounds)
ax2.legend(fontsize=10)
ax2.grid(True, alpha=0.3, linestyle=':', axis='y')

# Add value labels
for bars in [bars3, bars4]:
    for bar in bars:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.1f}%', ha='center',
                va='bottom' if height > 0 else 'top', fontsize=8)

plt.tight_layout()

# Save
from pathlib import Path
output_path = Path("output/analysis/s3_vs_astar_comparison.png")
plt.savefig(output_path, dpi=150, bbox_inches='tight')
print(f"Plot saved to: {output_path}")

plt.savefig(output_path.with_suffix('.pdf'), bbox_inches='tight')
print(f"PDF saved to: {output_path.with_suffix('.pdf')}")

plt.show()

# Print detailed analysis
print("\n" + "="*80)
print("S3 vs Astar 详细分析")
print("="*80)

print("\n1. S3 模型 (Step 12680):")
print(f"   最终 loss: 1.2651")
print(f"   最低 loss: 1.2404")

print("\n2. 继续训练 3 轮 Astar 后 (Step 34860):")
print(f"   最终 loss: 1.2502  (降低 0.0149, -1.2%)")
print(f"   最低 loss: 1.2157  (降低 0.0247, -2.0%)")

print("\n3. 关键观察:")
print(f"   ✅ Astar3 确实使 loss 进一步降低")
print(f"   ⚠️  但降幅有限 (1-2%)")
print(f"   ⚠️  Astar1 和 Astar2 的最终 loss 反而高于 S3")
print(f"   ✅ 只有 Astar3 最终超过了 S3")

print("\n4. 训练效率:")
s3_steps = 12680
astar3_steps = 34860
total_astar_steps = astar3_steps - s3_steps
print(f"   S3 训练步数:     {s3_steps:,}")
print(f"   Astar 额外步数:  {total_astar_steps:,}  (+{total_astar_steps/s3_steps*100:.0f}%)")
print(f"   Loss 改进:       1.2% (最终) / 2.0% (最低)")
print(f"   效率比:         每 10k 步改进 ~0.06% loss")

print("\n5. 结论:")
print(f"   📊 从纯 loss 角度：Astar3 略优于 S3")
print(f"   ⚡ 从效率角度：S3 性价比更高 (用 1/3 步数达到接近效果)")
print(f"   🎯 从泛化角度：需要在验证集/测试集上评估")
