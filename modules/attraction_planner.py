# -*- coding: utf-8 -*-
"""
Attraction planner module.

Public interface kept unchanged:
    get_attractions(user_profile) -> list[dict]

Expected user_profile keys:
    departure
    destination
    days
    budget
    style

Returned attraction item fields:
    name, area, main_category, tags, indoor_outdoor, rain_friendly,
    rain_backup, duration_hours, best_time, rating, description, detail,
    why_recommended, image_url
"""
import json
import os
import re
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None


USE_GEMINI = os.getenv("ATTRACTION_USE_GEMINI", "0").lower() in [
    "1",
    "true",
    "yes",
]
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "attractions"

MAIN_CATEGORIES = [
    "文化歷史",
    "購物",
    "美食",
    "夜景",
    "自然",
    "咖啡廳",
    "室內景點",
]

FEATURE_TAGS = [
    "拍照",
    "雨天適合",
    "親子",
    "夜生活",
    "散步",
    "文青",
    "購物",
    "美食",
    "室內",
    "戶外",
]


def _safe_slug(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^a-z0-9_\-\u4e00-\u9fff]", "", text)
    return text or "unknown_destination"


def _cache_path_for(user_profile: dict) -> Path:
    destination = (user_profile or {}).get("destination") or "unknown_destination"
    return CACHE_DIR / f"{_safe_slug(destination)}.json"


def get_attractions(user_profile):
    """Return attractions based on the passed user_profile.

    This function now really respects user_profile["destination"] even when
    Gemini is disabled.  Each destination has its own cache file, preventing
    Seoul fallback data from leaking into Los Angeles or other destinations.
    """
    user_profile = user_profile or {}
    cache_path = _cache_path_for(user_profile)

    if not USE_GEMINI and cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as f:
            return normalize_attractions(json.load(f))

    if USE_GEMINI:
        try:
            attractions = get_attractions_from_gemini(user_profile)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with cache_path.open("w", encoding="utf-8") as f:
                json.dump(normalize_attractions(attractions), f, ensure_ascii=False, indent=2)
            return normalize_attractions(attractions)
        except Exception:
            return normalize_attractions(get_fallback_attractions(user_profile))

    return normalize_attractions(get_fallback_attractions(user_profile))


def get_attractions_from_gemini(user_profile):
    if genai is None or types is None:
        raise RuntimeError("尚未安裝 google-genai，無法使用 Gemini 景點推薦。")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("尚未設定 GEMINI_API_KEY。")

    client = genai.Client(api_key=api_key)

    prompt = f"""
請根據以下旅遊資訊，推薦 6 個適合的當地景點。

出發地：
{user_profile.get("departure", "")}

目的地：
{user_profile.get("destination", "")}

旅遊天數：
{user_profile.get("days", "")}

預算：
{user_profile.get("budget", "")}

旅行風格與已選住宿：
{user_profile.get("style", "")}

請只輸出 JSON array，不要 Markdown。

每個景點都必須包含：
name, area, main_category, tags, indoor_outdoor, rain_friendly, rain_backup, duration_hours, best_time, rating, description, detail, why_recommended, image_url

main_category 必須只能從以下選擇一個：
文化歷史、購物、美食、夜景、自然、咖啡廳、室內景點

tags 必須是 array，每個景點可包含 1～4 個標籤。
tags 只能從以下選擇：
拍照、雨天適合、親子、夜生活、散步、文青、購物、美食、室內、戶外

indoor_outdoor 只能填：室內、戶外、半戶外
rain_friendly 必須是 true 或 false
rain_backup 請填雨天可替代的景點名稱，若本身適合雨天則填空字串
duration_hours 請填數字，例如 1.5、2、3

image_url 如果沒有可靠圖片，可以回傳空字串。
rating 請使用 4.0 到 5.0 之間的小數。
請務必符合目的地，不要輸出其他城市或其他國家的景點。
""".strip()

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.5,
            response_mime_type="application/json",
        ),
    )

    return json.loads(response.text)


def normalize_main_category(raw_category):
    text = str(raw_category or "")
    for category in MAIN_CATEGORIES:
        if category in text:
            return category
    return "文化歷史"


def normalize_tags(raw_tags):
    if isinstance(raw_tags, list):
        text = " ".join(str(tag) for tag in raw_tags)
    else:
        text = str(raw_tags or "")

    tags = []
    for tag in FEATURE_TAGS:
        if tag in text:
            tags.append(tag)
    return list(dict.fromkeys(tags))


def normalize_attraction(item):
    item = dict(item or {})
    old_categories = item.get("categories", item.get("category", ""))
    main_category = item.get("main_category") or normalize_main_category(old_categories)

    tags = item.get("tags") or normalize_tags(old_categories)
    tags = [str(tag) for tag in tags if str(tag).strip()]
    tags = [tag for tag in dict.fromkeys(tags) if tag in FEATURE_TAGS]

    indoor_outdoor = item.get("indoor_outdoor") or ""
    if not indoor_outdoor:
        if "室內" in tags or main_category == "室內景點":
            indoor_outdoor = "室內"
        elif "戶外" in tags or main_category in ["自然", "夜景"]:
            indoor_outdoor = "戶外"
        else:
            indoor_outdoor = "半戶外"

    rain_friendly = item.get("rain_friendly")
    if rain_friendly is None:
        rain_friendly = indoor_outdoor == "室內" or "雨天適合" in tags

    duration_hours = item.get("duration_hours")
    if duration_hours is None:
        duration_text = str(item.get("duration") or "")
        match = re.search(r"\d+(?:\.\d+)?", duration_text)
        duration_hours = float(match.group(0)) if match else None

    item["main_category"] = main_category
    item["tags"] = tags
    item["indoor_outdoor"] = indoor_outdoor
    item["rain_friendly"] = bool(rain_friendly)
    item["rain_backup"] = item.get("rain_backup") or ""
    item["duration_hours"] = duration_hours
    item["why_recommended"] = item.get("why_recommended") or item.get("description") or ""
    return item


def normalize_attractions(attractions):
    return [normalize_attraction(item) for item in attractions or [] if isinstance(item, dict)]


def _destination_key(user_profile: dict) -> str:
    destination = str((user_profile or {}).get("destination") or "").lower()
    if any(word in destination for word in ["洛杉磯", "los angeles", "lax"]):
        return "los_angeles"
    if any(word in destination for word in ["紐約", "new york", "nyc", "jfk"]):
        return "new_york"
    if any(word in destination for word in ["東京", "tokyo"]):
        return "tokyo"
    if any(word in destination for word in ["大阪", "osaka"]):
        return "osaka"
    if any(word in destination for word in ["沖繩", "okinawa", "naha"]):
        return "okinawa"
    if any(word in destination for word in ["首爾", "seoul", "韓國", "korea"]):
        return "seoul"
    return "generic"


def get_fallback_attractions(user_profile=None):
    """Destination-aware fallback attractions.

    This keeps the module usable when Gemini quota is exhausted or disabled.
    """
    user_profile = user_profile or {}
    destination = user_profile.get("destination") or "目的地"
    key = _destination_key(user_profile)

    if key == "los_angeles":
        return [
            {
                "name": "Griffith Observatory",
                "area": "Griffith Park",
                "categories": ["夜景", "拍照", "自然"],
                "rating": 4.7,
                "duration": "1.5–2.5 小時",
                "best_time": "傍晚到夜晚",
                "description": "可以俯瞰洛杉磯市景與好萊塢標誌，適合拍照與看夜景。",
                "detail": "建議避開尖峰開車時段，若停車較滿可搭接駁或提早抵達。",
                "image_url": "",
            },
            {
                "name": "Santa Monica Pier",
                "area": "Santa Monica",
                "categories": ["海邊", "拍照", "輕鬆散步"],
                "rating": 4.6,
                "duration": "2–3 小時",
                "best_time": "下午到夕陽",
                "description": "經典海邊碼頭，有摩天輪、海景與周邊餐廳，適合放鬆行程。",
                "detail": "可和 Third Street Promenade 或 Venice Beach 排在同一天。",
                "image_url": "",
            },
            {
                "name": "The Getty Center",
                "area": "Brentwood",
                "categories": ["藝術", "建築", "拍照"],
                "rating": 4.8,
                "duration": "2–4 小時",
                "best_time": "上午或下午",
                "description": "建築、花園與藝術收藏都很有看點，適合喜歡文化與拍照的旅客。",
                "detail": "入館通常免費但停車需付費，建議先確認開放時間。",
                "image_url": "",
            },
            {
                "name": "Hollywood Walk of Fame",
                "area": "Hollywood",
                "categories": ["地標", "拍照", "娛樂"],
                "rating": 4.0,
                "duration": "1–1.5 小時",
                "best_time": "白天",
                "description": "第一次到洛杉磯可順路打卡的經典地標。",
                "detail": "周邊人潮較多，建議和 TCL Chinese Theatre、Hollywood & Highland 一起安排。",
                "image_url": "",
            },
            {
                "name": "The Broad",
                "area": "Downtown LA",
                "categories": ["藝術", "室內景點", "拍照"],
                "rating": 4.7,
                "duration": "1.5–2 小時",
                "best_time": "白天",
                "description": "現代藝術館，適合安排在市中心行程中。",
                "detail": "熱門展覽建議事先預約，附近可順排 Walt Disney Concert Hall。",
                "image_url": "",
            },
            {
                "name": "Grand Central Market",
                "area": "Downtown LA",
                "categories": ["美食", "室內景點", "在地體驗"],
                "rating": 4.5,
                "duration": "1–1.5 小時",
                "best_time": "午餐或晚餐",
                "description": "集合多種洛杉磯在地與異國小吃，適合和市中心景點串接。",
                "detail": "可和 Angels Flight、The Broad、Little Tokyo 排在同一天。",
                "image_url": "",
            },
        ]

    if key == "seoul":
        return [
            {
                "name": "景福宮",
                "area": "首爾鐘路區",
                "categories": ["文化歷史", "拍照"],
                "rating": 4.6,
                "duration": "1.5–2 小時",
                "best_time": "上午",
                "description": "首爾代表性宮殿，適合第一次到韓國的文化行程。",
                "detail": "可和北村韓屋村、三清洞安排在同一天。",
                "image_url": "",
            },
            {
                "name": "北村韓屋村",
                "area": "鐘路區",
                "categories": ["文化歷史", "拍照", "散步"],
                "rating": 4.4,
                "duration": "1.5-2 小時",
                "best_time": "上午或傍晚",
                "description": "保留傳統韓屋街景，適合拍照與感受首爾傳統生活氛圍。",
                "detail": "巷弄仍有居民生活，建議降低音量並避開過度打擾住宅區。",
                "image_url": "",
            },
            {
                "name": "明洞商圈",
                "area": "明洞",
                "categories": ["購物", "美食"],
                "rating": 4.5,
                "duration": "2–3 小時",
                "best_time": "下午到晚上",
                "description": "適合購物、街邊小吃與保養品採買。",
                "detail": "晚餐前後前往最熱鬧。",
                "image_url": "",
            },
            {
                "name": "漢江公園",
                "area": "汝矣島或盤浦一帶",
                "categories": ["自然", "散步", "夜景"],
                "rating": 4.6,
                "duration": "1.5-3 小時",
                "best_time": "傍晚到夜晚",
                "description": "適合放鬆、野餐、散步與欣賞城市河岸夜景。",
                "detail": "可依住宿位置選擇較順路的漢江公園段落，例如汝矣島或盤浦。",
                "image_url": "",
            },
            {
                "name": "弘大商圈",
                "area": "弘大",
                "categories": ["購物", "夜生活", "拍照"],
                "rating": 4.5,
                "duration": "2–3 小時",
                "best_time": "下午到晚上",
                "description": "年輕潮流商圈，適合逛街、咖啡廳與街頭表演。",
                "detail": "可安排在較輕鬆的一天晚上。",
                "image_url": "",
            },
            {
                "name": "Starfield Library",
                "area": "COEX Mall",
                "categories": ["室內景點", "拍照", "購物"],
                "rating": 4.5,
                "duration": "1-1.5 小時",
                "best_time": "白天或雨天備案",
                "description": "大型開放式書牆很有記憶點，適合作為室內景點與購物行程銜接。",
                "detail": "可和 COEX Mall、奉恩寺或江南周邊行程排在同一天。",
                "image_url": "",
            },
        ]

    return [
        {
            "name": f"{destination} 市中心地標散策",
            "area": destination,
            "categories": ["地標", "拍照", "散步"],
            "rating": 4.3,
            "duration": "1.5-2 小時",
            "best_time": "白天",
            "description": "依目前目的地產生的通用景點建議，適合做為第一天熟悉城市的行程。",
            "detail": "建議搭配住宿位置與大眾運輸路線調整實際順序。",
            "image_url": "",
        },
        {
            "name": f"{destination} 老街或歷史街區",
            "area": destination,
            "categories": ["文化歷史", "散步", "拍照"],
            "rating": 4.2,
            "duration": "1.5-2.5 小時",
            "best_time": "上午",
            "description": "適合了解當地文化脈絡，也能安排輕鬆步行與拍照。",
            "detail": "若當地有博物館、古城區或傳統市場，可優先替換成更精準的名稱。",
            "image_url": "",
        },
        {
            "name": f"{destination} 在地市場",
            "area": destination,
            "categories": ["美食", "在地體驗", "室內景點"],
            "rating": 4.2,
            "duration": "1-2 小時",
            "best_time": "午餐或晚餐",
            "description": "適合銜接美食搜尋，也能快速感受目的地的生活感。",
            "detail": "建議確認營業時間，部分市場週末或夜間更熱鬧。",
            "image_url": "",
        },
        {
            "name": f"{destination} 河岸或海邊散步區",
            "area": destination,
            "categories": ["自然", "散步", "夜景"],
            "rating": 4.1,
            "duration": "1.5-2.5 小時",
            "best_time": "傍晚",
            "description": "適合排在航班抵達後或較輕鬆的一天，降低交通與體力負擔。",
            "detail": "若目的地沒有海邊，可改成城市公園或河岸步道。",
            "image_url": "",
        },
        {
            "name": f"{destination} 藝術館或博物館",
            "area": destination,
            "categories": ["藝術", "室內景點", "文化歷史"],
            "rating": 4.2,
            "duration": "1.5-3 小時",
            "best_time": "白天或雨天備案",
            "description": "適合作為天候不佳時的備案，也能讓行程不只停留在購物與拍照。",
            "detail": "建議提前確認是否需預約或是否有休館日。",
            "image_url": "",
        },
        {
            "name": f"{destination} 觀景台或夜景點",
            "area": destination,
            "categories": ["夜景", "拍照", "地標"],
            "rating": 4.3,
            "duration": "1-2 小時",
            "best_time": "傍晚到夜晚",
            "description": "適合作為晚餐前後的收尾景點，增加旅程記憶點。",
            "detail": "若票價較高，建議和整體預算一起評估是否保留。",
            "image_url": "",
        },
    ]
