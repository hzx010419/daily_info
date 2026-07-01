#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
工具函数模块
"""

import os
import sys
import yaml
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import hashlib

def load_config(config_path: str = None) -> Dict[str, Any]:
    """
    加载配置
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置字典
    """
    default_config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "config.yaml"
    )
    
    config_path = config_path or default_config_path
    
    if not os.path.exists(config_path):
        logging.warning(f"配置文件不存在: {config_path}，使用默认配置")
        return get_default_config()
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 合并默认配置
        default_config = get_default_config()
        merged_config = merge_dicts(default_config, config)
        
        logging.info(f"成功加载配置文件: {config_path}")
        return merged_config
        
    except Exception as e:
        logging.error(f"加载配置文件失败: {e}")
        return get_default_config()

def get_default_config() -> Dict[str, Any]:
    """获取默认配置"""
    return {
        'rss': {
            'excel_file': '公众号列表.xlsx',
            'sheet_name': None,
            'columns': {
                'source_name': '公众号名称',
                'rss_link': 'RSS链接'
            },
            'max_concurrent': 5,
            'request_interval': 1.0,
            'timeout': 30
        },
        'filter': {
            'enable_ad_filter': True,
            'ad_keywords': [],
            'price_patterns': [],
            'contact_patterns': [],
            'max_url_count': 3,
            'title_ad_indicators': []
        },
        'summary': {
            'target_length': 250,
            'min_length': 200,
            'max_length': 300,
            'method': 'simple',
            'preserve_key_info': True,
            'max_sentences': 10
        },
        'document': {
            'font': {
                'name': '微软雅黑',
                'size': 10.5,
                'title_size': 16
            },
            'paragraph': {
                'line_spacing': 1.5,
                'space_before': 6,
                'space_after': 6
            },
            'separator': {
                'character': '—',
                'length': 60,
                'space_before': 15,
                'space_after': 10
            },
            'link_color': [0, 0, 255]
        },
        'output': {
            'directory': '../output',
            'filename_format': '每日资讯_%Y-%m-%d.docx',
            'keep_history': True,
            'max_history_files': 30
        },
        'logging': {
            'level': 'INFO',
            'file': '../logs/app.log',
            'max_file_size': 10,
            'backup_count': 5,
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        },
        'schedule': {
            'enabled': True,
            'run_time': '12:00',
            'timezone': 'Asia/Shanghai',
            'max_run_time': 30
        },
        'test': {
            'enabled': False,
            'max_sources': 5,
            'max_articles': 3,
            'verbose': True
        }
    }

def merge_dicts(default: Dict, custom: Dict) -> Dict:
    """
    深度合并两个字典
    
    Args:
        default: 默认字典
        custom: 自定义字典
        
    Returns:
        合并后的字典
    """
    for key, value in custom.items():
        if key in default:
            if isinstance(default[key], dict) and isinstance(value, dict):
                default[key] = merge_dicts(default[key], value)
            else:
                default[key] = value
        else:
            default[key] = value
    return default

def setup_logging(config: Dict[str, Any]) -> None:
    """
    设置日志
    
    Args:
        config: 日志配置
    """
    log_config = config.get('logging', {})
    
    # 创建日志目录
    log_file = log_config.get('file', '../logs/app.log')
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    
    # 设置日志级别
    level_name = log_config.get('level', 'INFO')
    level = getattr(logging, level_name.upper(), logging.INFO)
    
    # 配置日志格式
    log_format = log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 清除现有处理器
    logging.getLogger().handlers.clear()
    
    # 添加文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(log_format))
    logging.getLogger().addHandler(file_handler)
    
    # 添加控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(log_format))
    logging.getLogger().addHandler(console_handler)
    
    # 设置根日志级别
    logging.getLogger().setLevel(level)
    
    logging.info(f"日志系统已初始化，级别: {level_name}")

def format_timestamp(timestamp: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化时间戳
    
    Args:
        timestamp: 时间戳
        format_str: 格式字符串
        
    Returns:
        格式化后的时间字符串
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    
    return timestamp.strftime(format_str)

def calculate_md5(content: str) -> str:
    """
    计算内容的MD5哈希
    
    Args:
        content: 文本内容
        
    Returns:
        MD5哈希值
    """
    return hashlib.md5(content.encode('utf-8')).hexdigest()

def safe_filename(filename: str) -> str:
    """
    生成安全的文件名
    
    Args:
        filename: 原始文件名
        
    Returns:
        安全的文件名
    """
    # 替换不安全的字符
    unsafe_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for char in unsafe_chars:
        filename = filename.replace(char, '_')
    
    # 限制文件名长度
    max_length = 255
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        filename = name[:max_length - len(ext)] + ext
    
    return filename

def ensure_directory(path: str) -> bool:
    """
    确保目录存在
    
    Args:
        path: 目录路径
        
    Returns:
        是否成功
    """
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as e:
        logging.error(f"创建目录失败: {path}, 错误: {e}")
        return False

def read_excel_file(filepath: str, sheet_name: str = None) -> List[Dict]:
    """
    读取Excel文件
    
    Args:
        filepath: Excel文件路径
        sheet_name: 工作表名称
        
    Returns:
        数据列表
    """
    try:
        import pandas as pd
        
        if not os.path.exists(filepath):
            logging.error(f"Excel文件不存在: {filepath}")
            return []
        
        df = pd.read_excel(filepath, sheet_name=sheet_name)
        
        # 转换为字典列表
        data = df.to_dict('records')
        logging.info(f"成功读取Excel文件: {filepath}, 共{len(data)}条记录")
        
        return data
        
    except Exception as e:
        logging.error(f"读取Excel文件失败: {filepath}, 错误: {e}")
        return []

def write_json_file(data: Any, filepath: str, indent: int = 2) -> bool:
    """
    写入JSON文件
    
    Args:
        data: 数据
        filepath: 文件路径
        indent: 缩进
        
    Returns:
        是否成功
    """
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        
        logging.info(f"成功写入JSON文件: {filepath}")
        return True
        
    except Exception as e:
        logging.error(f"写入JSON文件失败: {filepath}, 错误: {e}")
        return False

def read_json_file(filepath: str) -> Optional[Any]:
    """
    读取JSON文件
    
    Args:
        filepath: 文件路径
        
    Returns:
        数据或None
    """
    try:
        if not os.path.exists(filepath):
            logging.warning(f"JSON文件不存在: {filepath}")
            return None
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logging.info(f"成功读取JSON文件: {filepath}")
        return data
        
    except Exception as e:
        logging.error(f"读取JSON文件失败: {filepath}, 错误: {e}")
        return None

def get_project_root() -> str:
    """
    获取项目根目录
    
    Returns:
        根目录路径
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_resource_path(relative_path: str) -> str:
    """
    获取资源文件路径
    
    Args:
        relative_path: 相对路径
        
    Returns:
        完整路径
    """
    project_root = get_project_root()
    return os.path.join(project_root, relative_path)