#!/bin/bash
# 每周资讯自动生成脚本（信息选题参考平台）
# 流程：读取本周（周一~周五）的每日资讯 docx，去重整合，生成每周资讯 docx
# 用法：
#   ./每周自动运行.sh              # 生成上一整周（默认 --last-week）
#   ./每周自动运行.sh --date 2026-06-30   # 指定某周

set -e
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$BASE_DIR/logs/weekly_run_$(date +%Y%m%d).log"

mkdir -p "$BASE_DIR/logs"

echo "=== 开始生成每周资讯：$(date +%Y-%m-%d\ %H:%M:%S) ===" | tee -a "$LOG_FILE"

cd "$BASE_DIR/每周资讯skill"
if [ "$#" -eq 0 ]; then
  python3 run.py --last-week 2>&1 | tee -a "$LOG_FILE"
else
  python3 run.py "$@" 2>&1 | tee -a "$LOG_FILE"
fi

echo "=== 完成：$(date +%H:%M:%S)，输出在 $BASE_DIR/每周资讯/ ===" | tee -a "$LOG_FILE"
