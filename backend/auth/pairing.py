"""
Device Pairing 认证与设备管理。
提取自 api_server.py，确保接口与原有逻辑一致。
"""
import json
import secrets
from datetime import datetime
from pathlib import Path

from flask import request


def load_devices(devices_file: Path) -> dict:
    """加载设备信息"""
    if devices_file and devices_file.exists():
        try:
            return json.loads(devices_file.read_text())
        except Exception:
            pass
    return {"paired": {}, "pending": {}}

def save_devices(devices_file: Path, data: dict):
    """保存设备信息"""
    if devices_file:
        devices_file.write_text(json.dumps(data, indent=2, default=str))

def get_request_device_id():
    """从请求中提取 device_id"""
    return (request.headers.get("X-Device-ID") or
            request.args.get("device_id") or
            request.cookies.get("pm_device_id"))

def generate_pairing_code():
    return secrets.token_urlsafe(16)

def add_pending_device(devices, device_id, device_name, ip):
    devices["pending"][device_id] = {
        "device_id": device_id,
        "device_name": device_name,
        "requested_at": datetime.now().isoformat(),
        "ip": ip,
    }

def approve_pairing(devices, device_id):
    pending = devices["pending"].pop(device_id)
    token = secrets.token_urlsafe(32)
    devices["paired"][device_id] = {
        **pending,
        "token": token,
        "status": "active",
        "approved_at": datetime.now().isoformat(),
        "token_delivered": False,
    }
    return token

def revoke_device(devices, device_id):
    if device_id in devices["paired"]:
        devices["paired"][device_id]["status"] = "revoked"
        return True
    return False

def remove_pending_device(devices, device_id):
    if device_id in devices["pending"]:
        devices["pending"].pop(device_id)
        return True
    return False
