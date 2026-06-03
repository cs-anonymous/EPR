#!/usr/bin/env python3
"""
Plot SFT training loss curve for all 6 rounds
"""

import json
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

# Log files
log_files = [
    "output/logs/sft_qwen35_08b_from_cpt_6rounds_3gpu_20260531.log",
    "output/logs/sft_qwen35_08b_resume_from_28000_20260602_205513.log",
    "output/logs/sft_qwen35_08b_resume_from_28000_fixed_20260602_230215.log",
]

# Parse all logs
all_data = []
for log_file in log_files:
    log_path = Path(log_file)
    if not log_path.exists():
        print(f"Warning: {log_file} not found")
        continue

    with open(log_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith('{'):
                continue
            try:
                data = json.loads(line)
                if 'global_step' in data and 'loss' in data:
                    all_data.append(data)
            except json.JSONDecodeError:
                continue

print(f"Total data points: {len(all_data)}")

# Sort by global_step
all_data.sort(key=lambda x: x['global_step'])

# Extract data
steps = [d['global_step'] for d in all_data]
losses = [d['loss'] for d in all_data]
rounds = [d.get('round', 'unknown') for d in all_data]

# Identify round boundaries
round_names = ['train_S1', 'train_S2', 'train_S3', 'train_Astar1', 'train_Astar2', 'train_Astar3']
round_boundaries = []
for i, r in enumerate(rounds):
    if i == 0 or r != rounds[i-1]:
        round_boundaries.append((steps[i], r))

print(f"Round boundaries: {round_boundaries}")

# Create figure
fig, ax = plt.subplots(figsize=(12, 5))

# Plot loss curve
ax.plot(steps, losses, linewidth=1.5, alpha=0.7, color='#2E86AB')

# Add round boundaries
colors = ['#A23B72', '#F18F01', '#C73E1D', '#6A994E', '#BC4B51', '#8B7E74']
for i, (step, round_name) in enumerate(round_boundaries):
    color = colors[i % len(colors)]
    ax.axvline(x=step, color=color, linestyle='--', linewidth=1.5, alpha=0.6)
    ax.text(step, ax.get_ylim()[1] * 0.98, round_name,
            rotation=90, verticalalignment='top', horizontalalignment='right',
            fontsize=10, color=color, weight='bold')

# Styling
ax.set_xlabel('Global Step', fontsize=12, weight='bold')
ax.set_ylabel('Training Loss', fontsize=12, weight='bold')
ax.set_title('SFT Training Loss - 6 Rounds (Qwen3.5-0.8B)', fontsize=14, weight='bold', pad=20)
ax.grid(True, alpha=0.3, linestyle=':', linewidth=0.8)
ax.set_xlim(left=0)

# Add statistics text
final_loss = losses[-1]
min_loss = min(losses)
min_loss_step = steps[losses.index(min_loss)]
stats_text = f'Final Loss: {final_loss:.4f}\nMin Loss: {min_loss:.4f} (step {min_loss_step})'
ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
        verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
        fontsize=10)

plt.tight_layout()

# Save figure
output_path = Path("output/analysis/sft_loss_curve_6rounds.png")
output_path.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(output_path, dpi=150, bbox_inches='tight')
print(f"\nPlot saved to: {output_path}")

# Also save PDF
pdf_path = output_path.with_suffix('.pdf')
plt.savefig(pdf_path, bbox_inches='tight')
print(f"PDF saved to: {pdf_path}")

plt.show()

# Print summary statistics
print("\n=== Summary Statistics ===")
print(f"Total steps: {steps[-1]}")
print(f"Total data points: {len(steps)}")
print(f"Initial loss: {losses[0]:.4f}")
print(f"Final loss: {losses[-1]:.4f}")
print(f"Min loss: {min_loss:.4f} at step {min_loss_step}")
print(f"Loss reduction: {losses[0] - losses[-1]:.4f} ({(losses[0] - losses[-1])/losses[0]*100:.2f}%)")

print("\n=== Per-Round Statistics ===")
for i, (step, round_name) in enumerate(round_boundaries):
    # Find data for this round
    if i < len(round_boundaries) - 1:
        next_step = round_boundaries[i+1][0]
        round_data = [(s, l) for s, l, r in zip(steps, losses, rounds) if s >= step and s < next_step]
    else:
        round_data = [(s, l) for s, l, r in zip(steps, losses, rounds) if s >= step]

    if round_data:
        round_steps, round_losses = zip(*round_data)
        print(f"{round_name}:")
        print(f"  Steps: {round_steps[0]} - {round_steps[-1]} ({len(round_steps)} points)")
        print(f"  Initial loss: {round_losses[0]:.4f}")
        print(f"  Final loss: {round_losses[-1]:.4f}")
        print(f"  Min loss: {min(round_losses):.4f}")
        print(f"  Reduction: {round_losses[0] - round_losses[-1]:.4f}")
