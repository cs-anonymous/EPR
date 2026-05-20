# Language CPT Training Notes

Last updated: 2026-05-19

## Current default

- Script: `cpt_language.sh`
- Model: `./Qwen3.5-4B`
- Dataset: `./PianoCoReS/CoReS/language_cpt_s2_shuffled.jsonl`
- GPUs: `0,1`

The current CPT flow uses the merged and shuffled JSONL file instead of pointing Swift at the `language_cpt_s2/` directory directly.

## FlashAttention decision

Project decision for language CPT: do not enable `flash_attn` by default.

Reason:

- `flash_attn` is now installable and usable in this environment.
- But the measured speedup for this workload is small.
- `packing + flash_attn` does not help here and adds a heavy preprocessing stage.
- Keeping the default training path simple is more valuable than chasing a small gain.

## Benchmarks on GPU2,3

All tests below were run on 2026-05-19 with the same model and dataset as the main CPT run, using short Swift benchmarks on GPUs `2,3`.

| Config | Result |
| --- | --- |
| baseline | `10.2 s/it` |
| `--attn_impl flash_attn` | `9.57 s/it` |
| `--packing true --packing_length 2048 --attn_impl flash_attn` | `9.84 s/it` |

Notes:

- `flash_attn` alone gave only a modest improvement, about 6%.
- `packing + flash_attn` was not better than `flash_attn` alone.
- `packing + flash_attn` also triggered a long packing preprocess pass before training started.

## Relevant logs

- Baseline: `log/bench_cpt_baseline_g23_20260519_161822.log`
- FlashAttention only: `log/bench_cpt_flashattnonly_g23_20260519_173311.log`
- Packing + FlashAttention: `log/bench_cpt_packing_flashattn_g23_20260519_173608.log`
- FlashAttention install/validation:
  - `log/bench_cpt_flashattn_postinstall_g23_20260519_173027.log`

## Recommendation

For future language CPT runs:

- keep the default script settings as they are
- do not add `--attn_impl flash_attn`
- do not add packing flags for this dataset/config

Only revisit this if the training stack changes in a meaningful way, for example a different GPU class, a different model size, or a different sequence packing strategy.
