"""
geocode.py  - 地理位置处理服务骨架。用于 gps_city/地名别名、文本归一等地理业务拓展。
"""

CITY_ALIASES = {
    "北京": ["Beijing", "beijing"],
    "上海": ["Shanghai", "shanghai"],
    "广州": ["Guangzhou", "guangzhou"],
    "深圳": ["Shenzhen", "shenzhen"],
    "成都": ["Chengdu", "chengdu"],
    "杭州": ["Hangzhou", "hangzhou"],
    "武汉": ["Wuhan", "wuhan"],
    "西安": ["Xi'an", "Xian", "xian"],
    "南京": ["Nanjing", "nanjing"],
    "重庆": ["Chongqing", "chongqing"],
    "天津": ["Tianjin", "tianjin"],
    "山西": ["Shanxi", "shanxi"],
    "北京海淀": ["Beijing Haidian", "Haidian"],
    "北京金融街": ["Beijing Jinrongjie", "Jinrongjie"],
    "北京景山": ["Beijing Jingshan", "Jingshan"],
    "江苏": ["Jiangsu", "jiangsu"],
    "苏州": ["Songling", "Suzhou", "suzhou"],
    "太原": ["Gutao", "gutao", "Taiyuan"],
}

def canonicalize_city(city_name):
    """
    统一标准化地名，方便索引和查询。
    Args:
        city_name (str): 地名原文本
    Returns:
        str: 标准化后的地名
    """
    return city_name
