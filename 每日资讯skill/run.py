#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
每日资讯Skill启动脚本
"""

import os
import sys
import argparse
import logging
from datetime import datetime

# ============== 前台运行时强制实时输出 ==============
# 1) 设置 PYTHONUNBUFFERED，子进程也不会缓冲
os.environ.setdefault('PYTHONUNBUFFERED', '1')

# 2) 让 stdout / stderr 变成行缓冲（即使被重定向到文件/管道，也实时 flush）
try:
    # Python 3.7+ 支持 reconfigure
    sys.stdout.reconfigure(line_buffering=True, encoding='utf-8')
    sys.stderr.reconfigure(line_buffering=True, encoding='utf-8')
except Exception:
    # 兼容旧环境：包装成行缓冲的 TextIOWrapper
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
    except Exception:
        pass

# 让内置 print 默认每次 flush，彻底避免前台终端"卡住不动"的观感
_orig_print = print
def print(*args, **kwargs):  # type: ignore[no-redef]
    kwargs.setdefault('flush', True)
    return _orig_print(*args, **kwargs)

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from main import main as run_main
from utils import setup_logging, load_config
from auth import get_api_key  # 授权 / 凭证获取

def setup_argparse() -> argparse.ArgumentParser:
    """设置命令行参数解析"""
    parser = argparse.ArgumentParser(
        description='每日资讯Skill - AI摘要 & 广告过滤版',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run.py                    # 正常模式运行
  python run.py --test             # 测试模式运行
  python run.py --config custom.yaml  # 使用自定义配置
  python run.py --verbose          # 详细输出模式
  python run.py --help             # 显示帮助信息
        """
    )
    
    parser.add_argument(
        '--test',
        action='store_true',
        help='测试模式，只处理前5个公众号'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='详细输出模式'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='自定义配置文件路径'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='自定义输出目录'
    )
    
    parser.add_argument(
        '--log-level',
        type=str,
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help='日志级别'
    )
    
    parser.add_argument(
        '--excel',
        type=str,
        default=None,
        help='自定义Excel文件路径（包含公众号RSS链接）'
    )

    parser.add_argument(
        '--reauth',
        action='store_true',
        help='清除已保存的凭证，重新输入授权码与 API 密钥'
    )

    return parser

def test_mode() -> bool:
    """测试模式运行"""
    print("=" * 70)
    print("每日资讯Skill - 测试模式")
    print("=" * 70)

    try:
        # 修改环境变量标识测试模式
        os.environ['DAILY_NEWS_TEST_MODE'] = '1'

        # 导入并运行简化版本
        from src.main import main as test_main

        # 运行测试
        success = test_main()

        if success:
            print("\n[成功] 测试模式运行成功！")
            print("   所有功能正常，可以切换到正常模式运行。")
        else:
            print("\n[失败] 测试模式运行失败！")
            print("   请检查错误信息并修复问题。")

        return success

    except Exception as e:
        print(f"\n[错误] 测试模式运行异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def setup_environment(args):
    """设置运行环境"""
    # 设置环境变量
    if args.test:
        os.environ['DAILY_NEWS_TEST_MODE'] = '1'
    
    if args.verbose:
        os.environ['DAILY_NEWS_VERBOSE'] = '1'
    
    # 加载配置
    config = load_config(args.config)
    
    # 覆盖配置中的日志级别
    if 'logging' in config:
        config['logging']['level'] = args.log_level
    
    # 覆盖输出目录
    if args.output and 'output' in config:
        config['output']['directory'] = args.output
    
    # 设置日志
    setup_logging(config)
    
    return config

def main():
    """主函数"""
    parser = setup_argparse()
    args = parser.parse_args()

    # 显示欢迎信息
    print("=" * 70)
    print("每日资讯Skill - 智能资讯收集系统")
    print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    try:
        # ============== 授权 / 获取 API 密钥 ==============
        # 作者本机：自动加载预置 Key，不弹任何提示
        # 他人电脑：首次需要输入授权码 + 自己的 API Key，之后自动加载
        api_key = get_api_key(force_reauth=args.reauth)
        if not api_key:
            print("\n[错误] 未获取到有效的 API 密钥，程序退出。")
            return False
        # 通过环境变量把 Key 注入主程序，避免参数链路改造过深
        os.environ['DEEPSEEK_API_KEY'] = api_key

        # 测试模式
        if args.test:
            return test_mode()

        # 正常模式
        print("\n启动每日资讯收集任务...")

        # 设置环境
        config = setup_environment(args)

        # 显示配置摘要
        if args.verbose:
            print("\n配置摘要:")
            print(f"  - 数据源: {config.get('rss', {}).get('excel_file', 'N/A')}")
            print(f"  - 输出目录: {config.get('output', {}).get('directory', 'N/A')}")
            print(f"  - 日志级别: {config.get('logging', {}).get('level', 'INFO')}")
            print(f"  - 广告过滤: {'启用' if config.get('filter', {}).get('enable_ad_filter', True) else '禁用'}")
            print(f"  - AI摘要: {config.get('summary', {}).get('method', 'simple')}")

        # 运行主程序，传递自定义Excel文件路径
        success = run_main(args.excel)

        if success:
            print("\n" + "=" * 70)
            print("[完成] 任务执行成功！")
            print("=" * 70)

            # 显示输出文件位置
            output_dir = config.get('output', {}).get('directory', 'output')
            output_dir = os.path.join(os.path.dirname(__file__), output_dir)

            print(f"\n输出文件位于: {output_dir}")
            print("\n提示: 请在需要时运行本程序生成每日资讯")

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