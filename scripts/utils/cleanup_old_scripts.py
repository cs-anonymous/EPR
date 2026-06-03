#!/usr/bin/env python3
"""Clean up old redundant scripts after pipeline refactoring.

This script will DELETE the following old scripts:
  - build_score_abcx.py (replaced by 01_build_score_abcx.py)
  - rebuild_score_assets_from_metadata.py (split into 02_* and 03_*)
  - build_annotated_score_tsv.py (merged into 03_write_score_assets.py)
  - build_pianocores_miditsv.py (replaced by 04_project_performance_tsv.py)
  - regenerate_all_pipeline.py (replaced by run_pipeline.py)
  - copy_score_abcx_to_miditsv.py (no longer needed)

WARNING: This is destructive! Make sure the new scripts work before running this.
"""

from pathlib import Path

OLD_SCRIPTS = [
    "build_score_abcx.py",
    "rebuild_score_assets_from_metadata.py",
    "build_annotated_score_tsv.py",
    "build_pianocores_miditsv.py",
    "regenerate_all_pipeline.py",
    "copy_score_abcx_to_miditsv.py",
]

def main():
    scripts_dir = Path(__file__).parent

    print("=" * 80)
    print("OLD SCRIPTS CLEANUP")
    print("=" * 80)
    print("\nThe following scripts will be DELETED:\n")

    for script in OLD_SCRIPTS:
        path = scripts_dir / script
        status = "EXISTS" if path.exists() else "NOT FOUND"
        print(f"  [{status}] {script}")

    print("\n" + "=" * 80)
    print("WARNING: This action cannot be undone!")
    print("=" * 80)

    response = input("\nType 'DELETE' to confirm deletion: ")

    if response != "DELETE":
        print("\nCancelled. No files were deleted.")
        return 0

    print("\nDeleting old scripts...")
    deleted = 0

    for script in OLD_SCRIPTS:
        path = scripts_dir / script
        if path.exists():
            path.unlink()
            print(f"  ✓ Deleted: {script}")
            deleted += 1
        else:
            print(f"  ⊘ Not found: {script}")

    print(f"\n✓ Cleanup complete. Deleted {deleted} files.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
