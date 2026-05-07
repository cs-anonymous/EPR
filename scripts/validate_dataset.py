#!/usr/bin/env python3
"""
验证生成的数据集

检查：
1. JSON 文件数量
2. 数据完整性
3. 格式正确性
"""

import json
from pathlib import Path
from collections import defaultdict


def validate_json_file(json_path: Path) -> dict:
    """验证单个 JSON 文件"""
    try:
        data = json.loads(json_path.read_text())

        # 检查必需字段
        required_fields = ['metadata', 'abcx_header', 'midi_tsv_header', 'segments']
        for field in required_fields:
            if field not in data:
                return {'valid': False, 'error': f'缺少字段: {field}'}

        # 检查 metadata
        metadata_fields = ['title', 'composer', 'performer', 'num_segments']
        for field in metadata_fields:
            if field not in data['metadata']:
                return {'valid': False, 'error': f'metadata 缺少字段: {field}'}

        # 检查 segments
        if len(data['segments']) != data['metadata']['num_segments']:
            return {'valid': False, 'error': f'segments 数量不匹配'}

        # 检查每个 segment
        for seg in data['segments']:
            seg_fields = ['id', 'start_measure', 'end_measure', 'abcx_body', 'midi_tsv_data']
            for field in seg_fields:
                if field not in seg:
                    return {'valid': False, 'error': f'segment 缺少字段: {field}'}

        return {
            'valid': True,
            'num_segments': len(data['segments']),
            'composer': data['metadata']['composer'],
            'title': data['metadata']['title'],
            'performer': data['metadata']['performer']
        }

    except Exception as e:
        return {'valid': False, 'error': str(e)}


def validate_dataset(dataset_dir: Path):
    """验证整个数据集"""
    json_files = list(dataset_dir.rglob("*.json"))
    json_files = [f for f in json_files if f.name != "dataset_stats.json"]

    print(f"找到 {len(json_files)} 个 JSON 文件")

    valid_count = 0
    invalid_count = 0
    total_segments = 0

    composer_stats = defaultdict(int)
    errors = []

    for json_path in json_files:
        result = validate_json_file(json_path)

        if result['valid']:
            valid_count += 1
            total_segments += result['num_segments']
            composer_stats[result['composer']] += 1
        else:
            invalid_count += 1
            errors.append((json_path.name, result['error']))

    print(f"\n验证结果:")
    print(f"  有效文件: {valid_count}")
    print(f"  无效文件: {invalid_count}")
    print(f"  总片段数: {total_segments}")
    print(f"  平均每文件片段数: {total_segments / valid_count if valid_count > 0 else 0:.1f}")

    print(f"\n作曲家统计:")
    for composer, count in sorted(composer_stats.items(), key=lambda x: -x[1])[:10]:
        print(f"  {composer}: {count} 个配对")

    if errors:
        print(f"\n错误列表:")
        for filename, error in errors[:10]:
            print(f"  {filename}: {error}")

    # 读取统计文件
    stats_path = dataset_dir / "dataset_stats.json"
    if stats_path.exists():
        stats = json.loads(stats_path.read_text())
        print(f"\n数据集统计 (dataset_stats.json):")
        print(f"  总作品数: {stats['total_abcx_files']}")
        print(f"  总配对数: {stats['total_pairs']}")
        print(f"  总片段数: {stats['total_segments']}")
        print(f"  平均每配对片段数: {stats['avg_segments_per_pair']:.1f}")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python validate_dataset.py <dataset_dir>")
        sys.exit(1)

    dataset_dir = Path(sys.argv[1])
    validate_dataset(dataset_dir)
