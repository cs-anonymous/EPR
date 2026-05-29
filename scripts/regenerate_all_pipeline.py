#!/usr/bin/env python3
"""
Complete pipeline regeneration following docs/score_performance_alignment_tikz.tex workflow.

This script regenerates all score and performance assets:
1. score.abcx (from XML/MXL where available)
2. score_aligned.abcx + structure.json + score.mid.tsv (from score_metadata.csv)
3. performance.mid.tsv (from performance_Astar_metadata.csv and performance_S_metadata.csv)

Usage:
    python scripts/regenerate_all_pipeline.py --jobs 32
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_command(cmd: list[str], description: str, allow_partial_failure: bool = False) -> None:
    """Run a command and handle errors."""
    print("\n" + "=" * 80)
    print(f"STEP: {description}")
    print("=" * 80)
    print(f"Command: {' '.join(str(c) for c in cmd)}")
    print()

    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        if allow_partial_failure:
            print(f"\n⚠ WARNING: {description} completed with some failures (exit code {result.returncode})")
            print("Continuing with next step...")
        else:
            print(f"\n❌ ERROR: {description} failed with exit code {result.returncode}", file=sys.stderr)
            sys.exit(result.returncode)
    else:
        print(f"\n✓ {description} completed successfully")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=32,
        help="Number of parallel workers (default: 32)",
    )
    parser.add_argument(
        "--pianocore-root",
        type=Path,
        default=Path("PianoCoRe"),
        help="PianoCoRe root directory (default: PianoCoRe)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/miditsv"),
        help="Output directory for generated files (default: data/miditsv)",
    )
    parser.add_argument(
        "--skip-score-abcx",
        action="store_true",
        help="Skip Step 1: building score.abcx from XML/MXL",
    )
    parser.add_argument(
        "--skip-score-assets",
        action="store_true",
        help="Skip Step 2-3: building score_aligned.abcx and score.mid.tsv",
    )
    parser.add_argument(
        "--skip-performance-s",
        action="store_true",
        help="Skip Step 4a: building performance TSV for S-tier",
    )
    parser.add_argument(
        "--skip-performance-astar",
        action="store_true",
        help="Skip Step 4b: building performance TSV for A*-tier",
    )

    args = parser.parse_args()

    print("=" * 80)
    print("COMPLETE PIPELINE REGENERATION")
    print("=" * 80)
    print(f"Jobs: {args.jobs}")
    print(f"PianoCoRe root: {args.pianocore_root}")
    print(f"Output directory: {args.output_dir}")
    print()

    # Step 1: Build score.abcx from XML/MXL directly to output directory
    if not args.skip_score_abcx:
        run_command(
            [
                sys.executable,
                "scripts/build_score_abcx.py",
                "--raw-dir", str(args.pianocore_root / "raw"),
                "--output-dir", str(args.output_dir),  # Output directly to data/miditsv
                "--jobs", str(args.jobs),
                "--force",
            ],
            "Step 1: Build score.abcx from XML/MXL",
            allow_partial_failure=True,  # Allow some files to fail (e.g., corrupted zips)
        )
    else:
        print("\n⊘ Skipping Step 1: Build score.abcx from XML/MXL")

    # Step 2-3: Build score_aligned.abcx, structure.json, and score.mid.tsv
    if not args.skip_score_assets:
        run_command(
            [
                sys.executable,
                "scripts/rebuild_score_assets_from_metadata.py",
                "--metadata", "data/score_metadata.csv",
                "--pianocore-root", str(args.pianocore_root),
                "--jobs", str(args.jobs),
            ],
            "Step 2-3: Build score_aligned.abcx, structure.json, and score.mid.tsv",
        )

    # Step 3.5: Build annotated score MIDI TSV
    if not args.skip_score_assets:
        run_command(
            [
                sys.executable,
                "scripts/build_annotated_score_tsv.py",
                "--metadata", "data/score_metadata.csv",
                "--pianocore-root", str(args.pianocore_root),
                "--jobs", str(args.jobs),
                "--overwrite",
            ],
            "Step 3.5: Build annotated score MIDI TSV",
        )
    else:
        print("\n⊘ Skipping Step 2-3 and 3.5: Build score assets")

    # Step 4a: Build performance.mid.tsv for S-tier performances
    if not args.skip_performance_s:
        run_command(
            [
                sys.executable,
                "scripts/build_pianocores_miditsv.py",
                "--metadata", "data/performance_S_metadata.csv",
                "--pianocore-root", str(args.pianocore_root),
                "--output-dir", str(args.output_dir),
                "--jobs", str(args.jobs),
                "--tier", "all",
                "--overwrite-tsv",
            ],
            "Step 4a: Build performance.mid.tsv for S-tier",
        )
    else:
        print("\n⊘ Skipping Step 4a: Build performance TSV for S-tier")

    # Step 4b: Build performance.mid.tsv for A*-tier performances
    if not args.skip_performance_astar:
        run_command(
            [
                sys.executable,
                "scripts/process_astar_performances.py",
                "--metadata", "data/performance_Astar_metadata.csv",
                "--pianocore-root", str(args.pianocore_root),
                "--output-dir", str(args.output_dir),
                "--jobs", str(args.jobs),
                "--overwrite-tsv",
            ],
            "Step 4b: Build performance.mid.tsv for A*-tier",
        )
    else:
        print("\n⊘ Skipping Step 4b: Build performance TSV for A*-tier")

    print("\n" + "=" * 80)
    print("✓ COMPLETE PIPELINE REGENERATION FINISHED")
    print("=" * 80)
    print("\nAll assets have been regenerated:")
    print("  • score.abcx (from XML/MXL)")
    print("  • score_aligned.abcx (aligned with H/M structure)")
    print("  • structure.json (H/M hierarchy)")
    print("  • score.mid.tsv (score MIDI in TSV format)")
    print("  • performance.mid.tsv (performance MIDI in TSV format)")
    print(f"\nOutput location: {args.output_dir}")


if __name__ == "__main__":
    main()
