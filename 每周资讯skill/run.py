#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
每周资讯Skill启动脚本（升级版）
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta

# ============== 前台运行时强制实时输出 ==============
os.environ.setdefault('PYTHONUNBUFFERED', '1')

try:
    sys.stdout.reconfigure(line_buffering=True, encoding='utf-8')
    sys.stderr.reconfigure(line_buffering=True, encoding='utf-8')
except Exception:
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
    except Exception:
        pass

_orig_print = print
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    return _orig_print(*args, **kwargs)

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from main import main as run_main
from auth import get_api_key


def setup_argparse() -> argparse.ArgumentParser:
    """设置命令行参数解析"""
    parser = argparse.ArgumentParser(
        description='每周资讯Skill - AI去重整合版（升级版）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run.py                    # 处理本周资讯
  python run.py --date 2026-04-13  # 处理指定日期所在周的资讯
  python run.py --last-week        # 处理上周资讯
  python run.py --daily-dir "D:/每日资讯"  # 指定每日资讯目录
  python run.py --output "D:/每周资讯"     # 指定输出目录
  python run.py --reauth           # 重新授权
  python run.py --help             # 显示帮助信息
        """
    )
    
    parser.add_argument('--date', type=str, default=None,
                        help='目标日期（格式：YYYY-MM-DD），默认为今天')
    parser.add_argument('--last-week', action='store_true',
                        help='处理上周资讯')
    parser.add_argument('--daily-dir', type=str, default=None,
                        help='每日资讯文件目录路径')
    parser.add_argument('--output', type=str, default=None,
                        help='输出目录路径')
    parser.add_argument('--verbose', action='store_true',
                        help='详细输出模式')
    parser.add_argument('--log-level', type=str,
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO', help='日志级别')
    parser.add_argument('--reauth', action='store_true',
                        help='清除已保存的凭证，重新输入授权码与API密钥')
    
    return parser


def main():
    """主函数"""
    parser = setup_argparse()
    args = parser.parse_args()

    print("=" * 70)
    print("每周资讯Skill - 智能资讯整合系统（升级版）")
    print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    try:
        # ============== 授权 / 获取 API 密钥 ==============
        api_key = get_api_key(force_reauth=args.reauth)
        if not api_key:
            print("\n[错误] 未获取到有效的 API 密钥，程序退出。")
            return False
        os.environ['DEEPSEEK_API_KEY'] = api_key

        # 解析目标日期
        target_date = None
        if args.last_week:
            target_date = datetime.now() - timedelta(days=7)
            print(f"\n处理上周资讯（目标日期: {target_date.strftime('%Y-%m-%d')}）")
        elif args.date:
            try:
                target_date = datetime.strptime(args.date, '%Y-%m-%d')
                print(f"\n处理指定周资讯（目标日期: {target_date.strftime('%Y-%m-%d')}）")
            except ValueError:
                print(f"\n[错误] 日期格式不正确: {args.date}")
                print("请使用格式: YYYY-MM-DD（例如: 2026-04-13）")
                return False
        else:
            print("\n处理本周资讯")

        # 设置日志级别
        if args.verbose or args.log_level == 'DEBUG':
            logging.getLogger().setLevel(logging.DEBUG)
            print("  [详细模式已启用]")

        print("\n启动每周资讯整合任务...")

        success = run_main(
            target_date=target_date,
            custom_daily_dir=args.daily_dir,
            custom_output_dir=args.output
        )

        if success:
            print("\n" + "=" * 70)
            print("[完成] 任务执行成功！")
            print("=" * 70)
        else:
            print("\n" + "=" * 70)
            print("[错误] 任务执行失败！")
            print("=" * 70)
            print("\n请检查错误日志并排除问题")

        return success

    except KeyboardInterrupt:
        print("\n\n用户中断操作")
        return False

    except Exception as e:
        print(f"\n程序执行异常: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
