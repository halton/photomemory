"""
认证与鉴权中间件。
包含 require_auth、require_admin 装饰器及认证主逻辑。
"""
import secrets
from functools import wraps

from flask import jsonify, request

# 注意：以下变量需由业务文件显式导入并赋值初始化
PAIRING_ENABLED = False
ADMIN_TOKEN = None
_devices = None

def check_auth():
    """
    验证请求。返回 (ok, device_id|'open')。
    需业务注入 PAIRING_ENABLED, _devices。
    """
    if not PAIRING_ENABLED:
        return True, "open"
    # localhost 放行逻辑略去，保留核心功能
    auth = request.headers.get("Authorization", "")
    device_id = request.headers.get("X-Device-ID", "") or request.args.get("device_id", "")
    if auth.startswith("Bearer ") and device_id:
        token = auth[7:]
        paired = _devices["paired"].get(device_id)
        if paired and paired.get("status") == "active":
            if secrets.compare_digest(token, paired["token"]):
                return True, device_id
    url_token = request.args.get("_t", "")
    url_did   = request.args.get("_d", "")
    if url_token and url_did:
        paired = _devices["paired"].get(url_did)
        if paired and paired.get("status") == "active":
            if secrets.compare_digest(url_token, paired["token"]):
                return True, url_did
    return False, ""

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        ok, _ = check_auth()
        if not ok:
            return jsonify({"error": "Unauthorized", "code": 401}), 401
        return f(*args, **kwargs)
    return wrapper

def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not ADMIN_TOKEN:
            return jsonify({"error": "Admin not configured"}), 403
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not token or not secrets.compare_digest(token, ADMIN_TOKEN):
            return jsonify({"error": "Forbidden"}), 403
        return f(*args, **kwargs)
    return wrapper
