#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
授权与凭证管理模块
=====================================================================
设计目标：
  1. 作者本机（MAC + 硬件 UUID 任一匹配 .machine_fingerprint 中的白名单）
     → 直接读取作者预置的 API Key，免输授权码、免输 Key、免任何提示。
  2. 他人电脑首次运行：要求输入
        - 6 位授权码（固定 654321）
        - 他自己的 DeepSeek API Key
     校验通过后，用授权码派生密钥对 API Key 进行 AES-GCM 加密，
     存放到用户主目录 ~/.daily_news_skill/credentials.enc，下次自动加载。
  3. 他人后续运行：自动从 credentials.enc 解密读取 Key，无需再次输入。
  4. 提供 reauth() 接口，支持 `python run.py --reauth` 重置凭证。

模块外部仅暴露：
    get_api_key(force_reauth: bool = False) -> str
    is_local_machine() -> bool

实现说明：
  - 不依赖任何第三方加密库，全部使用 Python 标准库：
      hashlib (PBKDF2 派生密钥) + 自实现 AES-GCM 等价方案 →
      为了零依赖，这里采用 "PBKDF2 派生 32 字节密钥 + HMAC-SHA256 完整性
      校验 + 标准库 secrets 生成 nonce + 简单 XOR 流加密" 的混合方案。
      虽然不是教科书 AES，但满足"非作者拿到 credentials.enc 也无法
      还原 API Key（需要授权码 + 完整性校验）"的目标，且零依赖。
  - 如果以后想升级到真正的 AES-GCM，只需 pip install cryptography
    并替换 _encrypt / _decrypt 两个函数即可，对外接口不变。
"""

from __future__ import annotations

import os
import sys
import json
import uuid
import base64
import getpass
import hashlib
import hmac
import secrets
import subprocess
from pathlib import Path
from typing import Optional, Tuple

# =====================================================================
# 常量
# =====================================================================

# 固定授权码（6 位）。如需修改，请同步修改打包说明文档。
AUTHORIZATION_CODE: str = "654321"

# 凭证文件存放位置（用户主目录下的隐藏目录，跨用户隔离）
_CRED_DIR: Path = Path.home() / ".daily_news_skill"
_CRED_FILE: Path = _CRED_DIR / "credentials.enc"

# 本机白名单文件（位于 skill 根目录，作者机器上预置；打包给他人前应删除）
_SKILL_ROOT: Path = Path(__file__).resolve().parent.parent
_FINGERPRINT_FILE: Path = _SKILL_ROOT / ".machine_fingerprint"

# 允许的最大授权码尝试次数
_MAX_CODE_ATTEMPTS: int = 5

# PBKDF2 迭代次数（足够慢以阻止暴力破解，但启动时无感知）
_PBKDF2_ITERATIONS: int = 200_000


# =====================================================================
# 本机指纹识别
# =====================================================================

def _get_mac_fingerprint() -> str:
    """获取本机 MAC 地址（小写 16 进制，无分隔符）。失败时返回空串。"""
    try:
        node = uuid.getnode()
        # 第 41 位 = 1 表示是随机生成（getnode fallback），不算可靠指纹
        if (node >> 40) & 0x01:
            return ""
        return format(node, "012x")
    except Exception:
        return ""


def _get_hardware_uuid() -> str:
    """
    获取硬件 UUID（macOS / Linux / Windows 兼容）。
    优先 macOS 的 IOPlatformUUID（最稳，重装系统都不变）。
    """
    # macOS
    if sys.platform == "darwin":
        try:
            output = subprocess.check_output(
                ["ioreg", "-d2", "-c", "IOPlatformExpertDevice"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode("utf-8", errors="ignore")
            for line in output.splitlines():
                if "IOPlatformUUID" in line:
                    # 行形如：    "IOPlatformUUID" = "767FEDE9-..."
                    parts = line.split('"')
                    if len(parts) >= 4:
                        return parts[-2].strip().upper()
        except Exception:
            pass
    # Linux：/etc/machine-id 或 /var/lib/dbus/machine-id
    elif sys.platform.startswith("linux"):
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    val = f.read().strip()
                    if val:
                        return val.upper()
            except Exception:
                continue
    # Windows：注册表 MachineGuid
    elif sys.platform.startswith("win"):
        try:
            import winreg  # type: ignore
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "MachineGuid")
                if val:
                    return str(val).upper()
        except Exception:
            pass

    return ""


def _current_fingerprints() -> Tuple[str, str]:
    """返回当前机器的 (mac, hardware_uuid)。"""
    return _get_mac_fingerprint(), _get_hardware_uuid()


def is_local_machine() -> bool:
    """
    判断当前是否为作者本机：
    任一指纹（MAC 或硬件 UUID）匹配 .machine_fingerprint 中记录即视为本机。
    """
    if not _FINGERPRINT_FILE.exists():
        return False
    try:
        data = json.loads(_FINGERPRINT_FILE.read_text(encoding="utf-8"))
        whitelist_macs = {str(m).lower() for m in data.get("macs", []) if m}
        whitelist_uuids = {str(u).upper() for u in data.get("uuids", []) if u}
        author_key = data.get("author_api_key", "") or ""

        cur_mac, cur_uuid = _current_fingerprints()
        mac_hit = bool(cur_mac) and cur_mac.lower() in whitelist_macs
        uuid_hit = bool(cur_uuid) and cur_uuid.upper() in whitelist_uuids

        # 必须同时存在作者预置的 key 才算"本机"，否则也要走授权流程
        return (mac_hit or uuid_hit) and bool(author_key)
    except Exception:
        return False


def _load_author_api_key() -> Optional[str]:
    """从 .machine_fingerprint 读取作者预置的 API Key（仅本机有效）。"""
    if not _FINGERPRINT_FILE.exists():
        return None
    try:
        data = json.loads(_FINGERPRINT_FILE.read_text(encoding="utf-8"))
        key = data.get("author_api_key", "") or ""
        return key or None
    except Exception:
        return None


# =====================================================================
# 凭证加密 / 解密（零依赖实现）
# =====================================================================

def _derive_key(passcode: str, salt: bytes) -> bytes:
    """用授权码 + 盐派生 32 字节加密密钥。"""
    return hashlib.pbkdf2_hmac(
        "sha256", passcode.encode("utf-8"), salt, _PBKDF2_ITERATIONS, dklen=32
    )


def _encrypt(plaintext: str, passcode: str) -> bytes:
    """
    使用授权码派生的密钥加密明文。
    输出二进制结构：
        magic(4) || salt(16) || nonce(16) || hmac(32) || ciphertext(N)
    其中 ciphertext 由 keystream XOR 而来，keystream =
        SHA256(key || nonce || counter_be32) 拼接，足够覆盖明文长度。
    hmac = HMAC-SHA256(key, salt || nonce || ciphertext)
    """
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    key = _derive_key(passcode, salt)

    pt = plaintext.encode("utf-8")
    # 生成足够长的 keystream
    keystream = bytearray()
    counter = 0
    while len(keystream) < len(pt):
        block = hashlib.sha256(
            key + nonce + counter.to_bytes(4, "big")
        ).digest()
        keystream.extend(block)
        counter += 1
    keystream = bytes(keystream[: len(pt)])
    ciphertext = bytes(a ^ b for a, b in zip(pt, keystream))

    tag = hmac.new(key, salt + nonce + ciphertext, hashlib.sha256).digest()

    return b"DNS1" + salt + nonce + tag + ciphertext


def _decrypt(blob: bytes, passcode: str) -> Optional[str]:
    """解密；授权码错误或文件被篡改时返回 None。"""
    if len(blob) < 4 + 16 + 16 + 32 or blob[:4] != b"DNS1":
        return None
    salt = blob[4:20]
    nonce = blob[20:36]
    tag = blob[36:68]
    ciphertext = blob[68:]

    key = _derive_key(passcode, salt)
    expected = hmac.new(key, salt + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        return None

    keystream = bytearray()
    counter = 0
    while len(keystream) < len(ciphertext):
        block = hashlib.sha256(
            key + nonce + counter.to_bytes(4, "big")
        ).digest()
        keystream.extend(block)
        counter += 1
    keystream = bytes(keystream[: len(ciphertext)])
    pt = bytes(a ^ b for a, b in zip(ciphertext, keystream))
    try:
        return pt.decode("utf-8")
    except UnicodeDecodeError:
        return None


# =====================================================================
# 凭证文件读写
# =====================================================================

def _save_credentials(api_key: str, passcode: str) -> None:
    """加密保存 API Key。"""
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    blob = _encrypt(api_key, passcode)
    payload = base64.b64encode(blob).decode("ascii")
    _CRED_FILE.write_text(payload, encoding="utf-8")
    try:
        os.chmod(_CRED_FILE, 0o600)  # 仅当前用户可读写
    except Exception:
        pass


def _load_credentials(passcode: str) -> Optional[str]:
    """解密读取 API Key；不存在或失败返回 None。"""
    if not _CRED_FILE.exists():
        return None
    try:
        payload = _CRED_FILE.read_text(encoding="utf-8").strip()
        blob = base64.b64decode(payload)
        return _decrypt(blob, passcode)
    except Exception:
        return None


def _clear_credentials() -> None:
    """删除已保存的凭证。"""
    try:
        if _CRED_FILE.exists():
            _CRED_FILE.unlink()
    except Exception:
        pass


# =====================================================================
# 交互流程
# =====================================================================

def _print_banner() -> None:
    line = "═" * 60
    print(line)
    print("  每日资讯 Skill — 首次运行授权")
    print(line)


def _ask_authorization_code() -> bool:
    """让用户输入 6 位授权码，最多 _MAX_CODE_ATTEMPTS 次。"""
    for attempt in range(1, _MAX_CODE_ATTEMPTS + 1):
        try:
            code = getpass.getpass(
                f"请输入 6 位授权码（{attempt}/{_MAX_CODE_ATTEMPTS}）："
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[授权取消]")
            return False
        if code == AUTHORIZATION_CODE:
            return True
        print("[✗] 授权码错误")
    print("[✗] 授权码尝试次数已用尽，程序退出")
    return False


def _ask_api_key() -> Optional[str]:
    """让用户输入自己的 DeepSeek API Key，校验最简单的格式。"""
    for _ in range(3):
        try:
            key = getpass.getpass("请输入您的 DeepSeek API 密钥：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[授权取消]")
            return None
        if not key:
            print("[✗] API 密钥不能为空")
            continue
        if not key.startswith("sk-") or len(key) < 20:
            print("[✗] 格式不正确，DeepSeek 密钥通常以 'sk-' 开头")
            continue
        return key
    print("[✗] API 密钥输入失败次数过多，程序退出")
    return None


def _interactive_setup() -> Optional[str]:
    """完整的首次授权交互；返回 API Key 或 None。"""
    _print_banner()
    if not _ask_authorization_code():
        return None
    api_key = _ask_api_key()
    if not api_key:
        return None
    _save_credentials(api_key, AUTHORIZATION_CODE)
    print("[✓] 授权成功，凭证已加密保存")
    print(f"[✓] 凭证位置：{_CRED_FILE}")
    print("[✓] 下次运行将自动使用，无需重复输入")
    print("═" * 60)
    return api_key


# =====================================================================
# 对外主接口
# =====================================================================

def get_api_key(force_reauth: bool = False) -> Optional[str]:
    """
    获取可用的 DeepSeek API Key。

    流程：
      1. 若 force_reauth=True，清除已有凭证并强制重新授权。
      2. 若当前为作者本机（指纹匹配），直接返回作者预置 Key。
      3. 否则尝试用固定授权码解密 ~/.daily_news_skill/credentials.enc。
      4. 解密失败或文件不存在，进入交互式授权流程。

    返回：API Key 字符串；用户取消或失败时返回 None（调用方应退出）。
    """
    if force_reauth:
        _clear_credentials()

    # 0) CI / 无人值守环境直通：若已通过环境变量提供 Key，直接使用，
    #    避免在 GitHub Actions 等无 TTY 环境里进入 getpass 交互而卡死。
    if not force_reauth:
        env_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
        if env_key:
            return env_key

    # 1) 作者本机直通
    if not force_reauth and is_local_machine():
        key = _load_author_api_key()
        if key:
            return key
        # 指纹文件存在但没填 key，降级到交互流程

    # 2) 已保存的他人凭证
    if not force_reauth:
        cached = _load_credentials(AUTHORIZATION_CODE)
        if cached:
            print("[✓] 已加载本地凭证")
            return cached

    # 3) 交互式首次授权
    return _interactive_setup()


# =====================================================================
# CLI 调试入口
# =====================================================================

if __name__ == "__main__":
    # 简单自检：打印当前指纹与本机识别结果
    mac, hwuuid = _current_fingerprints()
    print(f"当前 MAC : {mac}")
    print(f"当前 UUID: {hwuuid}")
    print(f"指纹文件 : {_FINGERPRINT_FILE} (exists={_FINGERPRINT_FILE.exists()})")
    print(f"凭证文件 : {_CRED_FILE} (exists={_CRED_FILE.exists()})")
    print(f"是否本机 : {is_local_machine()}")
