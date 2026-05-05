"""
Pydantic 请求/响应模型（首批仅迁移收藏相关）
"""
from typing import List, Optional

from pydantic import BaseModel


class FavoriteToggleResponse(BaseModel):
    favorited: bool

class PhotoInfo(BaseModel):
    id: int
    path: str
    filename: str
    taken_at: Optional[str]
    gps_lat: Optional[float]
    gps_lon: Optional[float]
    gps_city: Optional[str]
    width: Optional[int]
    height: Optional[int]
    is_screenshot: bool
    is_duplicate: bool
    dir_label: Optional[str]
    size: Optional[int]
    thumb_url: str
    original_url: str
    is_favorite: bool = True

class FavoritesResponse(BaseModel):
    results: List[PhotoInfo]
    total: int
    limit: int
    offset: int
