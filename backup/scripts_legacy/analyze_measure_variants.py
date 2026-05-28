#!/usr/bin/env python3
"""Analyze measure count variants across PianoCoRe performances.

For each piece, identify:
- Canonical measure count (most common version)
- Variant versions (likely with/without repeats)
- Statistics on how many performances use each version

Output:
- output/reports/variants_report.txt: Human-readable summary
- output/reports/variants_data.json: Machine-readable data for filtering
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


def parse_tsv_measure_count(tsv_path: Path) -> int:
    """Count M<number> markers in a TSV file."""
    count = 0
    with open(tsv_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("M"):
                count += 1
    return count


def analyze_piece(piece_dir: Path) -> dict:
    """Analyze all performances of one piece."""
    tsv_files = sorted(piece_dir.glob("*.mid.tsv"))
    if not tsv_files:
        return None

    measure_counts = defaultdict(list)
    for tsv in tsv_files:
        count = parse_tsv_measure_count(tsv)
        measure_counts[count].append(tsv.name)

    # Find canonical version (most common)
    sorted_counts = sorted(measure_counts.items(), key=lambda x: len(x[1]), reverse=True)
    canonical_count = sorted_counts[0][0]
    canonical_perfs = sorted_counts[0][1]

    variants = []
    for count, perfs in sorted_counts[1:]:
        ratio = count / canonical_count if canonical_count > 0 else 0
        variants.append({
            "measure_count": count,
            "performances": perfs,
            "count": len(perfs),
            "ratio": round(ratio, 2),
        })

    return {
        "piece_path": str(piece_dir.relative_to(piece_dir.parent.parent)),
        "canonical_measure_count": canonical_count,
        "canonical_performances": canonical_perfs,
        "canonical_count": len(canonical_perfs),
        "variants": variants,
        "has_variants": len(variants) > 0,
    }


def main():
    output_root = Path("PianoCoRe_output")
    if not output_root.exists():
        print(f"Error: {output_root} not found")
        return

    print("Scanning all pieces...")
    all_pieces = []
    for composer_dir in sorted(output_root.iterdir()):
        if not composer_dir.is_dir():
            continue
        for piece_dir in sorted(composer_dir.iterdir()):
            if not piece_dir.is_dir():
                continue
            result = analyze_piece(piece_dir)
            if result:
                all_pieces.append(result)

    # Filter to pieces with variants
    pieces_with_variants = [p for p in all_pieces if p["has_variants"]]

    # Generate report
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("PianoCoRe Measure Count Variants Analysis")
    report_lines.append("=" * 80)
    report_lines.append("")
    report_lines.append(f"Total pieces: {len(all_pieces)}")
    report_lines.append(f"Pieces with variants: {len(pieces_with_variants)} ({100*len(pieces_with_variants)/len(all_pieces):.1f}%)")
    report_lines.append("")

    # Categorize by likely cause
    exact_double = []
    near_double = []
    other_variants = []

    for piece in pieces_with_variants:
        has_double = False
        for var in piece["variants"]:
            ratio = var["ratio"]
            if 1.95 <= ratio <= 2.05:
                exact_double.append(piece)
                has_double = True
                break
            elif 1.8 <= ratio <= 2.2:
                near_double.append(piece)
                has_double = True
                break
        if not has_double:
            other_variants.append(piece)

    report_lines.append(f"Likely repeat sections (2x measures): {len(exact_double)}")
    report_lines.append(f"Near-double variants (1.8-2.2x): {len(near_double)}")
    report_lines.append(f"Other variants: {len(other_variants)}")
    report_lines.append("")
    report_lines.append("=" * 80)
    report_lines.append("Examples of Repeat Section Variants (2x measures)")
    report_lines.append("=" * 80)
    report_lines.append("")

    for piece in sorted(exact_double, key=lambda p: p["canonical_count"], reverse=True)[:20]:
        report_lines.append(f"{piece['piece_path']}")
        report_lines.append(f"  Canonical: {piece['canonical_measure_count']} measures ({piece['canonical_count']} performances)")
        for var in piece["variants"]:
            report_lines.append(f"  Variant:   {var['measure_count']} measures ({var['count']} performances, {var['ratio']}x)")
        report_lines.append("")

    report_lines.append("=" * 80)
    report_lines.append("Filtering Recommendations")
    report_lines.append("=" * 80)
    report_lines.append("")

    total_perfs = sum(p["canonical_count"] for p in all_pieces)
    total_perfs += sum(sum(v["count"] for v in p["variants"]) for p in all_pieces)

    canonical_only = sum(p["canonical_count"] for p in all_pieces)
    variant_perfs = total_perfs - canonical_only

    report_lines.append(f"Total performances: {total_perfs}")
    report_lines.append(f"Canonical versions: {canonical_only} ({100*canonical_only/total_perfs:.1f}%)")
    report_lines.append(f"Variant versions: {variant_perfs} ({100*variant_perfs/total_perfs:.1f}%)")
    report_lines.append("")
    report_lines.append("If you filter to canonical versions only:")
    report_lines.append(f"  - Keep: {canonical_only} performances")
    report_lines.append(f"  - Remove: {variant_perfs} performances")
    report_lines.append("")

    # Write report
    out_dir = Path("output/reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = out_dir / "variants_report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"Report written to {report_path}")

    # Write JSON data
    data = {
        "summary": {
            "total_pieces": len(all_pieces),
            "pieces_with_variants": len(pieces_with_variants),
            "total_performances": total_perfs,
            "canonical_performances": canonical_only,
            "variant_performances": variant_perfs,
        },
        "pieces": all_pieces,
    }

    json_path = out_dir / "variants_data.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Data written to {json_path}")

    print("")
    print(f"Found {len(pieces_with_variants)} pieces with measure count variants")
    print(f"  - {len(exact_double)} likely have repeat sections (2x measures)")
    print(f"  - {len(near_double)} have near-double variants")
    print(f"  - {len(other_variants)} have other variants")


if __name__ == "__main__":
    main()
