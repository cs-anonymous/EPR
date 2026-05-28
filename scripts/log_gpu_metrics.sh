#!/usr/bin/env bash
set -euo pipefail

OUT_FILE="${1:-}"
INTERVAL_SEC="${2:-5}"

if [[ -z "${OUT_FILE}" ]]; then
  echo "Usage: $0 OUTPUT_FILE [INTERVAL_SEC]" >&2
  exit 1
fi

mkdir -p "$(dirname "${OUT_FILE}")"
if [[ ! -f "${OUT_FILE}" ]]; then
  echo "timestamp,index,name,pstate,utilization_gpu,utilization_memory,memory_used_mb,memory_total_mb,power_draw_w,power_limit_w,temperature_gpu_c,fan_speed_pct" > "${OUT_FILE}"
fi

while true; do
  nvidia-smi \
    --query-gpu=timestamp,index,name,pstate,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,power.limit,temperature.gpu,fan.speed \
    --format=csv,noheader,nounits >> "${OUT_FILE}"
  sleep "${INTERVAL_SEC}"
done
