"""
geocode.py  - 地理位置处理服务。城市别名、拼音映射、文本归一化。
"""

CITY_ALIASES = {
    "北京": ["Beijing", "beijing", "bj", "peking"],
    "上海": ["Shanghai", "shanghai", "sh"],
    "广州": ["Guangzhou", "guangzhou", "gz", "canton"],
    "深圳": ["Shenzhen", "shenzhen", "sz"],
    "成都": ["Chengdu", "chengdu", "cd"],
    "杭州": ["Hangzhou", "hangzhou", "hz"],
    "武汉": ["Wuhan", "wuhan", "wh"],
    "西安": ["Xi'an", "Xian", "xian", "xa"],
    "南京": ["Nanjing", "nanjing", "nj"],
    "重庆": ["Chongqing", "chongqing", "cq"],
    "天津": ["Tianjin", "tianjin", "tj"],
    "山西": ["Shanxi", "shanxi", "sx"],
    "北京海淀": ["Beijing Haidian", "Haidian", "haidian", "海淀"],
    "北京金融街": ["Beijing Jinrongjie", "Jinrongjie", "jinrongjie", "金融街"],
    "北京景山": ["Beijing Jingshan", "Jingshan", "jingshan", "景山"],
    "江苏": ["Jiangsu", "jiangsu", "js"],
    "苏州": ["Songling", "Suzhou", "suzhou", "sz"],
    "太原": ["Gutao", "gutao", "Taiyuan", "taiyuan", "ty"],
    "长沙": ["Changsha", "changsha", "cs"],
    "厦门": ["Xiamen", "xiamen", "xm", "amoy"],
    "青岛": ["Qingdao", "qingdao", "qd"],
    "大连": ["Dalian", "dalian", "dl"],
    "昆明": ["Kunming", "kunming", "km"],
    "三亚": ["Sanya", "sanya", "sy"],
    "丽江": ["Lijiang", "lijiang", "lj"],
    "桂林": ["Guilin", "guilin", "gl"],
    "香港": ["Hong Kong", "hongkong", "hk"],
    "澳门": ["Macau", "macau", "macao", "mo"],
    "台北": ["Taipei", "taipei", "tp"],
    "东京": ["Tokyo", "tokyo"],
    "大阪": ["Osaka", "osaka"],
    "首尔": ["Seoul", "seoul"],
    "曼谷": ["Bangkok", "bangkok"],
    "新加坡": ["Singapore", "singapore"],
    "伦敦": ["London", "london"],
    "巴黎": ["Paris", "paris"],
    "纽约": ["New York", "newyork", "nyc"],
}

# 反向映射：英文/拼音 → 中文
_REVERSE_ALIASES = {}
for cn, aliases in CITY_ALIASES.items():
    for alias in aliases:
        _REVERSE_ALIASES[alias.lower()] = cn


def expand_search_terms(query: str) -> list:
    """
    将搜索词扩展为所有相关别名（中文→英文，英文→中文）
    """
    terms = [query]
    q_lower = query.lower()

    # 中文 → 英文别名
    for cn, aliases in CITY_ALIASES.items():
        if query in cn or cn in query:
            terms.extend(aliases)

    # 英文/拼音 → 中文
    if q_lower in _REVERSE_ALIASES:
        cn = _REVERSE_ALIASES[q_lower]
        terms.append(cn)
        terms.extend(CITY_ALIASES.get(cn, []))

    # 部分匹配
    for cn, aliases in CITY_ALIASES.items():
        for alias in aliases:
            if q_lower in alias.lower() and cn not in terms:
                terms.append(cn)
                break

    return list(dict.fromkeys(terms))  # 去重保序


def canonicalize_city(city_name):
    """统一标准化地名"""
    if not city_name:
        return city_name
    lower = city_name.lower().strip()
    if lower in _REVERSE_ALIASES:
        return _REVERSE_ALIASES[lower]
    return city_name
