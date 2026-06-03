#!/usr/bin/env python3
"""Process A* performances to generate MIDI TSV files.

Reads data/Astar_metadata.csv and processes all A* performances
that are not in CoRe-S, generating performance MIDI TSV files.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.align_score_performance import (
    process_metadata_task,
    _worker_init,
    _worker_process,
)


def load_midi_tsv_module():
    """Load midi_tsv.py module."""
    midi_tsv_script = ROOT / "wave-roll" / "midi_tsv.py"
    spec = importlib.util.spec_from_file_location("midi_tsv", midi_tsv_script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load midi_tsv.py from {midi_tsv_script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_tasks_from_astar_metadata(metadata_path: Path) -> list[dict]:
    """Build processing tasks from Astar_metadata.csv.

    Returns list of tasks in the format expected by process_metadata_task():
    {
        'score_path': str,       # relative path, e.g. 'Composer/Piece/score_PDMX_refined.mid'
        'piece_path': str,       # piece identifier, e.g. 'Composer/Piece'
        'suffix': str,           # '' or '_mini'
        'performances': [        # list of (perf_midi_path, align_path)
            ('Composer/Piece/Aria_xxx_refined.mid', 'Composer/Piece/Aria_xxx_refined_align.npz'),
            ...
        ],
        'abcx_path': str,        # full path, e.g. 'PianoCoRe/score/Composer/Piece/score.abcx'
    }
    """
    meta = pd.read_csv(metadata_path)

    # Filter out rows with missing required fields
    meta = meta[meta['score_abcx_path'].notna()]
    meta = meta[meta['refined_performance_midi_path'].notna()]
    meta = meta[meta['refined_alignment_path'].notna()]

    print(f"Filtered to {len(meta)} rows with all required fields")

    # Group by score to batch performances
    tasks_dict = defaultdict(list)

    for _, row in meta.iterrows():
        # Use refined paths (all A* performances have refined versions)
        perf_midi = row['refined_performance_midi_path']
        align_path = row['refined_alignment_path']
        abcx_path = row['score_abcx_path']

        # Determine score path - prefer refined if available
        if pd.notna(row['refined_score_midi_path']):
            score_midi = row['refined_score_midi_path']
        else:
            score_midi = row['score_midi_path']

        # Determine suffix based on score path
        suffix = '_mini' if '_mini' in str(score_midi) else ''

        # Build task key
        key = (score_midi, abcx_path, suffix)

        # Add performance to this score's task
        tasks_dict[key].append((perf_midi, align_path))

    # Convert to task list
    tasks = []
    for (score_midi, abcx_path, suffix), perfs in tasks_dict.items():
        # Extract piece_path from abcx_path
        # Format: PianoCoRe/score/Composer/Piece/score.abcx -> Composer/Piece
        abcx_rel = abcx_path.replace('PianoCoRe/score/', '').replace('/score.abcx', '')

        tasks.append({
            'score_path': score_midi,
            'piece_path': abcx_rel,
            'suffix': suffix,
            'performances': perfs,
            'abcx_path': abcx_path,
        })

    return tasks


def update_metadata_with_tsv_paths(
    metadata_path: Path,
    output_metadata_path: Path,
    output_dir: Path,
) -> None:
    """Update metadata CSV with generated TSV file paths."""
    meta = pd.read_csv(metadata_path)

    # Add tsv_path column
    tsv_paths = []

    for _, row in meta.iterrows():
        perf_midi = row['refined_performance_midi_path']
        abcx_path = row['score_abcx_path']

        # Skip rows with missing abcx_path
        if pd.isna(abcx_path):
            tsv_paths.append('')
            continue

        # Extract piece_path from abcx_path
        piece_rel = abcx_path.replace('PianoCoRe/score/', '').replace('/score.abcx', '')

        # Build TSV path: data/miditsv/Composer/Piece/perf_refined.mid.tsv
        perf_name = Path(perf_midi).name
        tsv_path = output_dir / piece_rel / f"{perf_name}.tsv"

        # Check if TSV file exists
        if tsv_path.exists():
            # Store relative path from data/
            tsv_rel = str(tsv_path.relative_to(output_dir.parent))
            tsv_paths.append(tsv_rel)
        else:
            tsv_paths.append('')

    meta['tsv_path'] = tsv_paths

    # Write updated metadata
    meta.to_csv(output_metadata_path, index=False)
    print(f"\n✓ Updated metadata written to: {output_metadata_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("data/performance_Astar_metadata.csv"),
        help="Path to Astar_metadata.csv",
    )
    parser.add_argument(
        "--pianocore-root",
        type=Path,
        default=Path("PianoCoRe"),
        help="PianoCoRe root directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/miditsv"),
        help="Output directory for TSV files",
    )
    parser.add_argument(
        "--output-metadata",
        type=Path,
        default=Path("data/performance_Astar_metadata_updated.csv"),
        help="Output metadata CSV with TSV paths",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=16,
        help="Number of parallel workers (default: 16, use 0 for CPU count)",
    )
    parser.add_argument(
        "--overwrite-tsv",
        action="store_true",
        help="Regenerate TSV files even when output already exists",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of score files to process (for testing)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Processing A* Performances")
    print("=" * 60)
    print(f"Metadata: {args.metadata}")
    print(f"PianoCoRe root: {args.pianocore_root}")
    print(f"Output dir: {args.output_dir}")
    print(f"Workers: {args.jobs}")

    # Build tasks
    print("\nBuilding tasks from metadata...")
    tasks = build_tasks_from_astar_metadata(args.metadata)

    if args.limit:
        tasks = tasks[:args.limit]

    total_perfs = sum(len(t['performances']) for t in tasks)
    print(f"Found {len(tasks)} score files, {total_perfs} performances to process")

    # Process tasks
    jobs = args.jobs
    if jobs == 0:
        import multiprocessing
        jobs = multiprocessing.cpu_count()

    if jobs <= 1:
        # Single-threaded processing
        midi_tsv = load_midi_tsv_module()
        success_count = 0
        tsv_count = 0

        for task in tqdm(tasks, desc="Processing"):
            n = process_metadata_task(
                task,
                midi_tsv,
                args.pianocore_root,
                args.output_dir,
                overwrite_tsv=args.overwrite_tsv,
            )
            success_count += 1 if n > 0 else 0
            tsv_count += n
    else:
        # Multi-threaded processing
        from multiprocessing import Pool, cpu_count

        n_workers = min(jobs, len(tasks), cpu_count())
        init_args = (args.pianocore_root, args.output_dir, args.overwrite_tsv)

        with Pool(n_workers, initializer=_worker_init, initargs=init_args) as pool:
            results = list(tqdm(
                pool.imap(_worker_process, tasks),
                total=len(tasks),
                desc="Processing",
            ))

        success_count = sum(1 for r in results if r > 0)
        tsv_count = sum(results)

    print(f"\n✓ Processing complete: {success_count} / {len(tasks)} scores successful")
    print(f"✓ Generated {tsv_count} TSV files")

    # Update metadata with TSV paths
    print("\nUpdating metadata with TSV paths...")
    update_metadata_with_tsv_paths(
        args.metadata,
        args.output_metadata,
        args.output_dir,
    )

    print("\n" + "=" * 60)
    print("✓ A* Performance Processing Complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
