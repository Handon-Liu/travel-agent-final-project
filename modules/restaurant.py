# -*- coding: utf-8 -*-
"""
restaurant.py - 全旅程餐飲規劃模組
========================================================

📦 模組職責：
    將所有與「餐廳生成」相關的邏輯獨立出來，包含：
    1. Pydantic Schema 定義（MealOption / DayDining / TripDiningPlan）
    2. Gemini API 呼叫與 RAG-like context 注入
    3. 地理鄰近性、飯店早餐優先等規則約束
    4. 結構化 JSON 解析

🔌 公開介面：
    get_dining_plan(user_profile: dict) -> dict

    輸入 user_profile 必要欄位：
        - destination_text   : 目的地敘述（例：「從台北出發，想去日本京都」）
        - travel_days        : 旅遊天數（int 或 str）
        - confirmed_style    : 旅行風格（例：「美食、文化、放鬆」）
        - selected_hotel     : 已選飯店敘述
        - attraction_pool    : 景點池（list of dict，含 name / area）

    回傳 dict 結構（符合 TripDiningPlan schema）：
        {
            "total_days": int,
            "overall_description": str,
            "days": [
                {
                    "day_number": int,
                    "day_theme": str,
                    "breakfast_options": [MealOption, ...],
                    "lunch_options": [MealOption, ...],
                    "dinner_options": [MealOption, ...]
                },
                ...
            ]
        }

🚀 用法範例：
    from restaurant import get_dining_plan
    plan = get_dining_plan(user_profile)

📦 環境需求：
    pip install google-genai pydantic
    環境變數 GEMINI_API_KEY 必須設定
"""

import json
import os
import re

try:
    from google import genai
    from google.genai import types
    from pydantic import BaseModel, Field
except ImportError:
    genai = None
    types = None
    BaseModel = None
    Field = None


# ==========================================
# Pydantic Schema - 全旅程餐飲計畫
# ==========================================
if BaseModel:
    class MealOption(BaseModel):
        """單一餐廳候選選項。"""
        title: str = Field(
            description="餐廳精確名稱（Google Maps 可搜尋）；若為飯店早餐則為「{飯店名稱} 飯店內用早餐」"
        )
        detail: str = Field(
            description="餐廳特色、料理風格、價位、與景點池中對應景點的步行距離"
        )

    class DayDining(BaseModel):
        """單日三餐的完整候選清單。"""
        day_number: int = Field(description="第幾天，從 1 開始遞增")
        day_theme: str = Field(description="當天的飲食主題或重點，搭配主要遊覽景點")
        breakfast_options: list[MealOption] = Field(
            description="早餐 3 個候選，第 1 個必須固定為飯店內用早餐",
            min_length=3,
            max_length=3,
        )
        lunch_options: list[MealOption] = Field(
            description="午餐 3 個候選，必須鄰近當日景點",
            min_length=3,
            max_length=3,
        )
        dinner_options: list[MealOption] = Field(
            description="晚餐 3 個候選，必須鄰近當日景點，氛圍適合晚餐",
            min_length=3,
            max_length=3,
        )

    class TripDiningPlan(BaseModel):
        """全旅程餐飲計畫主 Schema。"""
        total_days: int = Field(description="總天數，必須等於使用者指定的 travel_days")
        overall_description: str = Field(description="整體餐飲規劃介紹（2-3 句話）")
        days: list[DayDining] = Field(description="每一天的三餐候選，長度必須等於 total_days")
else:
    MealOption = None
    DayDining = None
    TripDiningPlan = None


# ==========================================
# 輔助函數
# ==========================================
def _get_gemini_client():
    """初始化並回傳 Gemini Client（每次呼叫都重新建立，避免共享狀態問題）。"""
    if genai is None:
        raise RuntimeError("尚未安裝 google-genai 套件，請執行：pip install google-genai pydantic")

    api_key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("Gemini API Key")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if not api_key:
        raise ValueError("尚未設定 GEMINI_API_KEY 環境變數。")

    return genai.Client(api_key=api_key)


def _parse_travel_days(user_profile: dict) -> int:
    """從 user_profile 中萃取出旅行天數。"""
    # 直接讀 travel_days
    days = user_profile.get("travel_days", "")
    if isinstance(days, int) and days > 0:
        return days
    if isinstance(days, str) and days.isdigit():
        return int(days)

    # 從 last_trip_params 字串萃取「X 天」
    params = user_profile.get("last_trip_params", "")
    match = re.search(r"(\d+)\s*天", params)
    if match:
        return int(match.group(1))

    # 預設 3 天
    return 3


def _format_attraction_pool(attraction_pool) -> str:
    """將景點池整理成結構化文字，供 prompt 使用。"""
    if not attraction_pool or not isinstance(attraction_pool, list):
        return "（未指定景點池）"

    lines = []
    for idx, a in enumerate(attraction_pool):
        if not isinstance(a, dict):
            continue
        name = a.get("name", "")
        area = a.get("area", "")
        categories = a.get("categories", [])
        if isinstance(categories, list):
            cat_str = ", ".join(categories)
        else:
            cat_str = str(categories)
        lines.append(
            f"  {idx + 1}. 「{name}」 - 所在區域：{area} - 屬性：{cat_str}"
        )
    return "\n".join(lines) if lines else "（景點池資料格式異常）"


def _build_prompt(user_profile: dict, travel_days: int) -> str:
    """組合餐飲規劃的主 prompt（RAG-like context 注入）。"""
    hotel = user_profile.get("selected_hotel", "")
    destination = user_profile.get("destination_text", "")
    style = user_profile.get("confirmed_style", "")
    attraction_pool_text = _format_attraction_pool(user_profile.get("attraction_pool", []))

    return f"""
請為旅客生成「{travel_days} 天完整餐飲計畫」，每天包含早、午、晚三餐，每餐提供 3 個候選餐廳。
總計需要生成 {travel_days} 個 Day 物件，每個 Day 包含 3 個 breakfast_options + 3 個 lunch_options + 3 個 dinner_options。

【目的地】
{destination}

【旅客風格】
{style}

【已選飯店】
{hotel}

【🎯 景點池 - 必去景點清單（午晚餐的地理參考點）】
{attraction_pool_text}

【天數】
{travel_days} 天（必須嚴格生成 {travel_days} 個 Day 物件）

---
⚠️ 絕對規則（不可違背）：

1. days 陣列長度必須等於 {travel_days}。total_days 必須等於 {travel_days}。

2. 每一天的 breakfast_options 第 1 個必須固定為「飯店內用早餐」：
   - title 範例：「{hotel} 飯店內用早餐」
   - detail 必須描述在已選飯店「{hotel}」內用早餐的便利性，
     例如：免出門、節省時間、可慢慢享用、適合作為一天行程的活力起點。
   - 同一個飯店早餐選項可在不同天的 breakfast_options[0] 重複出現。

3. 每一天的 breakfast_options 第 2、3 個必須是當地特色早餐店，
   且地理上鄰近飯店或景點池中的景點。

4. 🎯 核心規則：每一天的 lunch_options 與 dinner_options 全部 3 個選項：
   - 必須是 Google Maps 可搜尋到的真實餐廳。
   - 必須在地理位置上「合理圍繞」上方景點池中的景點，確保行程路線順暢。
   - 建議策略：將 {travel_days} 天的行程分配給景點池中不同景點，
     每天集中遊覽 1-2 個景點，午晚餐就選擇該景點周邊徒步可達的餐廳。
   - detail 中必須明確說明：
     a) 該餐廳對應景點池中的哪個景點
     b) 與該景點的步行距離（例：「距離 XXX 景點步行 5 分鐘」）
     c) 料理風格與價位

5. dinner_options 應該偏向「氛圍適合晚餐」的餐廳
   （如：氣氛佳、可慢慢用餐、特色料理、夜景）。

6. 不同天的 lunch 與 dinner 候選應該盡量「不重複」，讓旅客每天有新嘗試。

7. day_theme 用 1-2 句話描述當天飲食重點與對應的景點，
   例如：「Day 1 主攻景點 A 周邊，搭配傳統早餐 + 在地午餐 + 浪漫晚餐」。

8. overall_description 用 2-3 句話介紹整趟旅程的餐飲規劃理念，
   必須提及如何配合景點池的地理分布。
"""


# ==========================================
# 系統提示詞（共用常數）
# ==========================================
SYSTEM_INSTRUCTION = (
    "你是一位全球美食規劃專家，熟悉各國當地餐廳、米其林指南、在地特色料理與餐廳訂位文化。"
    "請嚴格輸出符合 Schema 結構的 JSON，不可有任何聊天字眼。"
    "推薦的餐廳必須是真實存在、可在 Google Maps 搜尋到的店家，絕對不可虛構。"
    "地理鄰近性是最高優先級：午餐與晚餐的推薦地點，"
    "必須從地理位置上合理圍繞在使用者已確認的『景點池』周邊，確保行程路線順暢。"
    "請將不同天分配給景點池中不同的景點作為當天的主要遊覽中心，"
    "餐廳就推薦那個景點周邊徒步可達的店家，避免讓旅客為了一餐長距離移動。"
    "每一天 breakfast_options 第 1 個必須固定為飯店內用早餐，這是不可違背的硬規則。"
    "Day 物件數量必須嚴格等於使用者指定的天數。"
)


# ==========================================
# 公開主函數
# ==========================================
def get_dining_plan(user_profile: dict) -> dict:
    """🎯 主入口：根據 user_profile 生成全旅程餐飲計畫。

    Args:
        user_profile: 包含 destination_text / travel_days / confirmed_style /
                      selected_hotel / attraction_pool 等欄位的字典。

    Returns:
        符合 TripDiningPlan schema 的字典，包含 total_days、overall_description、days。

    Raises:
        RuntimeError: 套件未安裝或 Gemini Client 初始化失敗。
        ValueError: GEMINI_API_KEY 未設定。
        json.JSONDecodeError: Gemini 回傳的 JSON 無法解析。
    """
    if BaseModel is None or TripDiningPlan is None:
        raise RuntimeError(
            "尚未安裝 pydantic 或 google-genai 套件。"
            "請執行：pip install google-genai pydantic"
        )

    client = _get_gemini_client()
    travel_days = _parse_travel_days(user_profile)
    prompt = _build_prompt(user_profile, travel_days)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.7,
            response_mime_type="application/json",
            response_schema=TripDiningPlan,
        ),
    )

    # 解析並回傳
    return json.loads(response.text)


# ==========================================
# 獨立測試入口（python restaurant.py）
# ==========================================
if __name__ == "__main__":
    # 測試用 mock profile
    mock_profile = {
        "destination_text": "從台北出發，想去日本京都",
        "travel_days": 3,
        "confirmed_style": "美食、文化體驗、不要太累",
        "selected_hotel": "京都站前東橫 INN（位於京都站旁，交通便利）",
        "attraction_pool": [
            {"name": "清水寺", "area": "東山區", "categories": ["文化歷史", "拍照"]},
            {"name": "金閣寺", "area": "北區", "categories": ["文化歷史", "拍照"]},
            {"name": "嵐山竹林", "area": "右京區", "categories": ["自然", "拍照"]},
            {"name": "錦市場", "area": "中京區", "categories": ["美食", "在地體驗"]},
            {"name": "伏見稻荷大社", "area": "伏見區", "categories": ["文化歷史", "拍照"]},
            {"name": "祇園", "area": "東山區", "categories": ["文化歷史", "夜生活"]},
        ],
    }

    print("🧪 測試 get_dining_plan()...")
    try:
        plan = get_dining_plan(mock_profile)
        print(f"✅ 成功！共 {plan.get('total_days')} 天")
        print(f"📝 整體說明：{plan.get('overall_description')}")
        for day in plan.get("days", []):
            print(f"\n📅 Day {day.get('day_number')}：{day.get('day_theme')}")
            print(f"   🌅 早餐：{day['breakfast_options'][0]['title']}")
            print(f"   🍱 午餐：{day['lunch_options'][0]['title']}")
            print(f"   🍷 晚餐：{day['dinner_options'][0]['title']}")
    except Exception as e:
        print(f"❌ 失敗：{e}")
