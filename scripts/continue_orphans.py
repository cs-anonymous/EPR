#!/usr/bin/env python3
"""Continue processing remaining orphan MIDI files."""
from __future__ import annotations

import sys
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))

from process_pianocore_a import PianoCoreProcessor

WORKER_PROC = None

def init_worker(root: str, out: str):
    global WORKER_PROC
    WORKER_PROC = PianoCoreProcessor(root, out)

def process_one(orphan) -> bool:
    return WORKER_PROC.process_orphan_midi(orphan)

def main():
    processor = PianoCoreProcessor('PianoCoRe', 'PianoCoRe_output')
    orphans = processor.discover_orphan_midis()

    remaining = []
    for o in orphans:
        out_dir = processor.output_dir / o.piece_dir.relative_to(processor.raw_root)
        tsv = out_dir / f'{o.perf_midi.name}.tsv'
        if not (tsv.exists() and tsv.stat().st_size > 0):
            remaining.append(o)

    print(f'待处理: {len(remaining)} / {len(orphans)}')

    with ProcessPoolExecutor(
        max_workers=16,
        initializer=init_worker,
        initargs=('PianoCoRe', 'PianoCoRe_output'),
    ) as executor:
        results = executor.map(process_one, remaining, chunksize=8)
        success = 0
        for ok in tqdm(results, total=len(remaining), desc='Orphan MIDI'):
            if ok:
                success += 1

    print(f'完成: {success} / {len(remaining)}')

if __name__ == '__main__':
    main()
