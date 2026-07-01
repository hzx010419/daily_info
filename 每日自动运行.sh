#!/bin/bash
# 每日自动运行脚本（信息选题参考平台）
# 流程：1. 爬取生成今日资讯 docx  2. AI 聚合构建网页数据  3. git push 触发 Vercel 部署
#
# 说明：整合后 build_all.py 直接把 JSON/docx 写入「信息日报/web/data」，
#       不再需要旧版从「写作线索日报」cp 复制的中间步骤。

set -e
# 平台根目录（脚本所在目录），无需硬编码绝对路径
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATE=$(date +%Y-%m-%d)
LOG_FILE="$BASE_DIR/logs/auto_run_$(date +%Y%m%d).log"

mkdir -p "$BASE_DIR/logs"

echo "=== 开始运行：$DATE $(date +%H:%M:%S) ===" | tee -a "$LOG_FILE"

# 1. 爬取生成今日资讯 docx（输出到 BASE_DIR/每日资讯/）
echo "[1/3] 生成今日资讯..." | tee -a "$LOG_FILE"
cd "$BASE_DIR/每日资讯skill"
python3 run.py 2>&1 | tee -a "$LOG_FILE"

# 2. AI 聚合构建网页数据（直接写入 信息日报/web/data，增量处理，已存在期次自动跳过）
echo "[2/3] 构建网页数据..." | tee -a "$LOG_FILE"
cd "$BASE_DIR/信息日报/build"
python3 build_all.py 2>&1 | tee -a "$LOG_FILE"

# 3. 推送到 GitHub（触发 Vercel 自动部署）
echo "[3/3] 推送到 GitHub..." | tee -a "$LOG_FILE"
cd "$BASE_DIR/信息日报"
git add web/data/
git commit -m "自动更新：$DATE" || echo "没有新变化" | tee -a "$LOG_FILE"
git push origin main 2>&1 | tee -a "$LOG_FILE"

echo "=== 运行完成：$(date +%H:%M:%S) ===" | tee -a "$LOG_FILE"
echo "Vercel 正在自动部署，预计 1-2 分钟后网页更新完成" | tee -a "$LOG_FILE"
