#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
授权与凭证管理模块（每周资讯Skill版本）
=====================================================================
设计目标：
  1. 作者本机（MAC + 硬件 UUID 任一匹配 .machine_fingerprint 中的白名单）
     → 直接读取作者预置的 API Key，免输授权码、免输 Key、免任何提示。
  2. 他人电脑首次运行：要求输入
        - 6 位授权码（固定 654321）
        - 他自己的 DeepSeek API Key
     校验通过后，用授权码派生密钥对 API Key 进行加密，
     存放到用户主目录 ~/.weekly_news_skill/credentials.enc，下次自动加载。
  3. 他人后续运行：自动从 credentials.enc 解密读取 Key，无需再次输入。
  4. 提供 reauth() 接口，支持 `python run.py --reauth` 重置凭证。
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

AUTHORIZATION_CODE: str = "654321"

_CRED_DIR: Path = Path.home() / ".weekly_news_skill"
_CRED_FILE: Path = _CRED_DIR / "credentials.enc"

_SKILL_ROOT: Path = Path(__file__).resolve().parent.parent
_FINGERPRINT_FILE: Path = _SKILL_ROOT / ".machine_fingerprint"

_MAX_CODE_ATTEMPTS: int = 5
_PBKDF2_ITERATIONS: int = 200_000


# =====================================================================
# 本机指纹识别
# =====================================================================

def _get_mac_fingerprint() -> str:
    try:
        node = uuid.getnode()
        if (node >> 40) & 0x01:
            return ""
        return format(node, "012x")
    except Exception:
        return ""


def _get_hardware_uuid() -> str:
    if sys.platform == "darwin":
        try:
            output = subprocess.check_output(
                ["ioreg", "-d2", "-c", "IOPlatformExpertDevice"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode("utf-8", errors="ignore")
            for line in output.splitlines():
                if "IOPlatformUUID" in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        return parts[-2].strip().upper()
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    val = f.read().strip()
                    if val:
                        return val.upper()
            except Exception:
                continue
    elif sys.platform.startswith("win"):
        try:
            import winreg
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
    return _get_mac_fingerprint(), _get_hardware_uuid()


def is_local_machine() -> bool:
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
        return (mac_hit or uuid_hit) and bool(author_key)
    except Exception:
        return False


def _load_author_api_key() -> Optional[str]:
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
    return hashlib.pbkdf2_hmac(
        "sha256", passcode.encode("utf-8"), salt, _PBKDF2_ITERATIONS, dklen=32
    )


def _encrypt(plaintext: str, passcode: str) -> bytes:
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    key = _derive_key(passcode, salt)
    pt = plaintext.encode("utf-8")
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
    return b"WNS1" + salt + nonce + tag + ciphertext


def _decrypt(blob: bytes, passcode: str) -> Optional[str]:
    if len(blob) < 4 + 16 + 16 + 32 or blob[:4] != b"WNS1":
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
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    blob = _encrypt(api_key, passcode)
    payload = base64.b64encode(blob).decode("ascii")
    _CRED_FILE.write_text(payload, encoding="utf-8")
    try:
        os.chmod(_CRED_FILE, 0o600)
    except Exception:
        pass


def _load_credentials(passcode: str) -> Optional[str]:
    if not _CRED_FILE.exists():
        return None
    try:
        payload = _CRED_FILE.read_text(encoding="utf-8").strip()
        blob = base64.b64decode(payload)
        return _decrypt(blob, passcode)
    except Exception:
        return None


def _clear_credentials() -> None:
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
    print("  每周资讯 Skill — 首次运行授权")
    print(line)


def _ask_authorization_code() -> bool:
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
    if force_reauth:
        _clear_credentials()
    if not force_reauth and is_local_machine():
        key = _load_author_api_key()
        if key:
            return key
    if not force_reauth:
        cached = _load_credentials(AUTHORIZATION_CODE)
        if cached:
            print("[✓] 已加载本地凭证")
            return cached
    return _interactive_setup()
