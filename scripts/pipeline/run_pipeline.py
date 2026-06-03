#!/usr/bin/env python3
"""Complete pipeline for generating all score and performance data.

This script executes all steps in sequence:
  Step 1: Build score.abcx from XML/MXL
  Step 2: Build H/M structure
  Step 3: Write score assets (aligned ABCX + annotated TSV)
  Step 4: Project H/M to performance TSV (S-tier and A*-tier)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], description: str, allow_partial_failure: bool = False) -> None:
    """Run a command and handle errors."""
    print(f"\n{'=' * 80}")
    print(f"▶ {description}")
    print(f"{'=' * 80}")
    print(f"Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd)

    if result.returncode != 0:
        if allow_partial_failure:
            print(f"\n⚠ {description} completed with some failures (exit code {result.returncode})")
        else:
            print(f"\n✗ {description} failed with exit code {result.returncode}")
            sys.exit(result.returncode)
    else:
        print(f"\n✓ {description} completed successfully")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Complete pipeline for generating all score and performance data"
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
        "--skip-step1",
        action="store_true",
        help="Skip Step 1: building score.abcx from XML/MXL",
    )
    parser.add_argument(
        "--skip-step2",
        action="store_true",
        help="Skip Step 2: building H/M structure and aligned ABCX",
    )
    parser.add_argument(
        "--skip-step3",
        action="store_true",
        help="Skip Step 3: writing annotated score TSV",
    )
    parser.add_argument(
        "--skip-step4-s",
        action="store_true",
        help="Skip Step 4 (S-tier): projecting to performance TSV",
    )
    parser.add_argument(
        "--skip-step4-astar",
        action="store_true",
        help="Skip Step 4 (A*-tier): projecting to performance TSV",
    )

    args = parser.parse_args()

    print("=" * 80)
    print("COMPLETE PIPELINE EXECUTION")
    print("=" * 80)
    print(f"Jobs: {args.jobs}")
    print(f"PianoCoRe root: {args.pianocore_root}")
    print(f"Output directory: {args.output_dir}")
    print()

    # Step 1: Build score.abcx from XML/MXL
    if not args.skip_step1:
        run_command(
            [
                sys.executable,
                "scripts/01_build_score_abcx.py",
                "--raw-dir", str(args.pianocore_root / "raw"),
                "--output-dir", str(args.output_dir),
                "--jobs", str(args.jobs),
                "--force",
            ],
            "Step 1: Build score.abcx from XML/MXL",
            allow_partial_failure=True,
        )
    else:
        print("\n⊘ Skipping Step 1: Build score.abcx from XML/MXL")

    # Step 2: Build H/M structure and write aligned ABCX
    if not args.skip_step2:
        run_command(
            [
                sys.executable,
                "scripts/02_build_hm_structure.py",
                "--metadata", "data/score_metadata.csv",
                "--pianocore-root", str(args.pianocore_root),
                "--jobs", str(args.jobs),
            ],
            "Step 2: Build H/M structure and write aligned ABCX",
        )
    else:
        print("\n⊘ Skipping Step 2: Build H/M structure")

    # Step 3: Write annotated score TSV
    if not args.skip_step3:
        run_command(
            [
                sys.executable,
                "scripts/03_write_annotated_tsv.py",
                "--metadata", "data/score_metadata.csv",
                "--pianocore-root", str(args.pianocore_root),
                "--jobs", str(args.jobs),
            ],
            "Step 3: Write annotated score TSV",
        )
    else:
        print("\n⊘ Skipping Step 3: Write annotated score TSV")

    # Step 4 (S-tier): Project to performance TSV
    if not args.skip_step4_s:
        run_command(
            [
                sys.executable,
                "scripts/04_project_performance_tsv.py",
                "--metadata", "data/performance_S_metadata.csv",
                "--pianocore-root", str(args.pianocore_root),
                "--output-dir", str(args.output_dir),
                "--jobs", str(args.jobs),
                "--tier", "all",
                "--overwrite-tsv",
            ],
            "Step 4 (S-tier): Project H/M to performance TSV",
        )
    else:
        print("\n⊘ Skipping Step 4 (S-tier): Project to performance TSV")

    # Step 4 (A*-tier): Project to performance TSV
    if not args.skip_step4_astar:
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
            "Step 4 (A*-tier): Project H/M to performance TSV",
        )
    else:
        print("\n⊘ Skipping Step 4 (A*-tier): Project to performance TSV")

    print("\n" + "=" * 80)
    print("✓ PIPELINE COMPLETED")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
