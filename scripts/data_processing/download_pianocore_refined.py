#!/usr/bin/env python3
"""
从 HuggingFace 下载 PianoCoRe refined 数据集
"""

from huggingface_hub import hf_hub_download
import os

# HuggingFace 数据集信息
repo_id = "SyMuPe/PianoCoRe"
filename = "PianoCoRe-1.0-refined.zip"
local_dir = "/home/sy/EPR/PianoCoRe"

print(f"从 HuggingFace 下载: {repo_id}/{filename}")
print(f"保存到: {local_dir}")

try:
    file_path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        repo_type="dataset",
        local_dir=local_dir,
        local_dir_use_symlinks=False
    )
    print(f"\n下载完成: {file_path}")
except Exception as e:
    print(f"\n下载失败: {e}")
    print("\n请手动从以下地址下载:")
    print(f"  https://huggingface.co/datasets/{repo_id}")
    print(f"  或 https://doi.org/10.5281/zenodo.19186016")
