"""
recommend.py - 智能相册推荐逻辑模块
核心入口: recommend_albums(user_id=None, top_k=5)
"""

from backend.db import get_db


def recommend_albums(user_id=None, top_k=5):
    """
    相册智能推荐示例：简单聚合，可基于热门/最新/打分等扩展
    当前实现：优先推荐最近最多照片的相册
    后续可接入个性化逻辑
    :param user_id: 可选用户参数
    :param top_k: 返回推荐数量
    :return: 推荐的相册列表（dict）
    """
    conn = get_db()
    # 示例1：最近更新且含照片多的相册
    q = '''
        SELECT a.id, a.name, a.description, a.created_at, a.updated_at,
               COUNT(ap.photo_id) as photo_count, a.cover_photo_id
        FROM albums a
        LEFT JOIN album_photos ap ON ap.album_id = a.id
        GROUP BY a.id
        HAVING photo_count > 0
        ORDER BY a.updated_at DESC, photo_count DESC
        LIMIT ?
    '''
    rows = conn.execute(q, (top_k,)).fetchall()
    albums = []
    for r in rows:
        albums.append({
            "id": r[0],
            "name": r[1],
            "description": r[2],
            "created_at": r[3],
            "updated_at": r[4],
            "photo_count": r[5],
            "cover_photo_id": r[6],
        })
    conn.close()
    return albums
