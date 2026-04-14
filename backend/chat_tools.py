#!/usr/bin/env python3
"""
PhotoMemory - Phase 5: OpenClaw Chat 工具接入
这个模块提供给 OpenClaw 调用的函数，让 AI 可以直接搜索照片
"""

import requests
import json
from urllib.parse import urlencode

API_BASE = "http://localhost:8765/api"


def search_photos(query: str = "", person: str = "", year: str = "",
                  month: str = "", limit: int = 12) -> dict:
    """
    搜索照片。返回结构化结果供 OpenClaw Chat 展示。

    参数:
      query  - 关键词（地点、目录标签等）
      person - 人物名字
      year   - 年份（如 "2023"）
      month  - 月份（如 "07"）
      limit  - 最多返回数量

    返回:
      {"total": int, "photos": [...], "summary": str}
    """
    params = {"limit": limit, "exclude_screenshots": "1"}
    if query: params["q"] = query
    if person: params["person"] = person
    if year: params["year"] = year
    if month: params["month"] = month

    try:
        r = requests.get(f"{API_BASE}/search", params=params, timeout=5)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"error": str(e), "total": 0, "photos": []}

    photos = []
    for p in data["results"]:
        date = ""
        if p.get("taken_at"):
            try:
                date = p["taken_at"][:10].replace(":", "-")
            except Exception:
                date = p["taken_at"][:10]
        photos.append({
            "id": p["id"],
            "filename": p["filename"],
            "date": date,
            "location": p.get("gps_city") or "",
            "dir": p.get("dir_label") or "",
            "thumb_url": f"http://localhost:8765{p['thumb_url']}",
            "original_url": f"http://localhost:8765{p['original_url']}",
            "is_duplicate": p.get("is_duplicate", False),
        })

    # 构建自然语言摘要
    parts = []
    if person: parts.append(f"人物「{person}」")
    if query: parts.append(f"关键词「{query}」")
    if year: parts.append(f"{year}年")
    if month: parts.append(f"{month}月")
    desc = "、".join(parts) if parts else "全部照片"

    summary = f"找到 {data['total']} 张照片（{desc}），展示前 {len(photos)} 张。"
    if data["total"] > limit:
        summary += f" 还有 {data['total'] - limit} 张，可缩小条件或增大 limit。"

    return {
        "total": data["total"],
        "photos": photos,
        "summary": summary,
    }


def get_stats() -> dict:
    """获取照片库统计信息"""
    try:
        r = requests.get(f"{API_BASE}/stats", timeout=5)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def list_persons() -> list:
    """列出所有已命名人物"""
    try:
        r = requests.get(f"{API_BASE}/persons", timeout=5)
        return r.json().get("persons", [])
    except Exception as e:
        return []


if __name__ == "__main__":
    # 测试
    print("=== 统计 ===")
    stats = get_stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2))

    print("\n=== 搜索最近照片 ===")
    result = search_photos(limit=5)
    print(result["summary"])
    for p in result["photos"]:
        print(f"  {p['date']} {p['filename']} {p['thumb_url']}")

    print("\n=== 人物列表 ===")
    persons = list_persons()
    for p in persons:
        print(f"  {p['name'] or '(未命名)'}: {p['face_count']} 张")
