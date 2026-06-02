# -*- coding: utf-8 -*-
import json
import os
import re
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from modules.flight_recommender import run as recommend_flight_options
from modules.hotel_recommender import run as recommend_hotel_options
from modules.attraction_planner import get_attractions


AIRPORTS = {
    "台北": "TPE",
    "桃園": "TPE",
    "高雄": "KHH",
    "台中": "RMQ",
    "首爾": "ICN",
    "釜山": "PUS",
    "濟州": "CJU",
    "東京": "NRT",
    "大阪": "KIX",
    "沖繩": "OKA",
    "福岡": "FUK",
    "札幌": "CTS",
    "香港": "HKG",
    "新加坡": "SIN",
    "曼谷": "BKK",
    "清邁": "CNX",
    "峴港": "DAD",
    "河內": "HAN",
    "胡志明市": "SGN",
    "富國島": "PQC",
    "峇里島": "DPS",
    "洛杉磯": "LAX",
    "紐約": "JFK",
    "舊金山": "SFO",
    "西雅圖": "SEA",
    "巴黎": "CDG",
    "羅馬": "FCO",
    "米蘭": "MXP",
}


COUNTRY_CITIES = {
    "韓國": ["首爾", "釜山", "濟州"],
    "日本": ["東京", "大阪", "沖繩", "福岡", "札幌"],
    "香港": ["香港"],
    "新加坡": ["新加坡"],
    "泰國": ["曼谷", "清邁"],
    "越南": ["峴港", "河內", "胡志明市", "富國島"],
    "印尼": ["峇里島"],
    "美國": ["洛杉磯", "紐約", "舊金山", "西雅圖"],
    "法國": ["巴黎"],
    "義大利": ["羅馬", "米蘭"],
}


def _date_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("/", "-")


def _days_between(start_date: str, end_date: str):
    try:
        from datetime import date

        start = date.fromisoformat(_date_text(start_date))
        end = date.fromisoformat(_date_text(end_date))
        return (end - start).days
    except Exception:
        return None


def _to_int(value, default=None):
    try:
        cleaned = re.sub(r"[^\d.]", "", str(value or ""))
        if cleaned == "":
            return default
        return int(float(cleaned))
    except (TypeError, ValueError):
        return default


def _to_bool(value, default=True):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in ["false", "0", "no", "否", "不用", "不需要"]:
        return False
    if text in ["true", "1", "yes", "是", "需要", "希望"]:
        return True
    return default


def _max_transfer_count(text):
    if text == "只要直飛":
        return 0
    if text == "可轉機一次":
        return 1
    if text == "可轉機兩次以上":
        return 2
    return None


def build_structured_request(form):
    departure_city = form.get("departure_city", "台北")
    destination_country = form.get("destination_country", "日本")
    destination_city = form.get("destination_city", "東京")
    transfer_preference = form.get("transfer_preference", "只要直飛")
    people = _to_int(form.get("people"), 1)
    calculated_nights = _days_between(form.get("start_date"), form.get("end_date"))
    if calculated_nights is not None and calculated_nights >= 0:
        travel_days = calculated_nights + 1
        nights = calculated_nights
    else:
        travel_days = _to_int(form.get("travel_days"))
        nights = _to_int(form.get("nights"), 0)
    hotel_per_night = _to_int(form.get("hotel_budget_twd_per_night"))
    total_budget = _to_int(form.get("total_budget_twd"))
    style_text = form.get("travel_style", "")
    preferred_area = form.get("preferred_area") or None
    if preferred_area == "不限":
        preferred_area = None
    max_transfer = _max_transfer_count(transfer_preference)

    styles = [
        item.strip()
        for item in re.split(r"[、,，\n]", style_text)
        if item.strip()
    ]

    return {
        "departure_city": departure_city,
        "departure_airport": AIRPORTS.get(departure_city),
        "destination_country": destination_country,
        "destination_city": destination_city,
        "arrival_airport": AIRPORTS.get(destination_city),
        "start_date": _date_text(form.get("start_date")),
        "start_date_text": None,
        "end_date": _date_text(form.get("end_date")),
        "travel_days": travel_days,
        "nights": nights,
        "people": people,
        "budget_twd": total_budget,
        "total_budget_twd": total_budget,
        "budget_level": None,
        "travel_style": styles,
        "preferred_pace": form.get("preferred_pace") or None,
        "baggage": form.get("baggage"),
        "flight_preferences": {
            "prefer_direct": max_transfer == 0,
            "transfer_preference": transfer_preference,
            "preferred_departure_time": form.get("preferred_departure_time") or None,
            "max_transfer_count": max_transfer,
            "flight_budget_twd_per_person": _to_int(form.get("flight_budget_twd_per_person")),
        },
        "hotel_preferences": {
            "preferred_area": preferred_area,
            "room_type": form.get("room_type") or None,
            "near_station": _to_bool(form.get("near_station"), True),
            "hotel_budget_twd_per_night": hotel_per_night,
            "hotel_budget_twd_total": hotel_per_night * nights if hotel_per_night and nights else None,
        },
        "food_preferences": {
            "favorite_types": styles,
            "avoid_types": [],
        },
        "special_notes": form.get("special_notes") or form.get("hotel_notes") or None,
    }


def missing_fields(structured):
    labels = {
        "departure_airport": "出發機場代碼",
        "arrival_airport": "抵達機場代碼",
        "start_date": "出發日",
        "end_date": "回程日",
        "travel_days": "天數",
        "people": "人數",
        "flight_budget_twd_per_person": "每人機票預算",
        "hotel_budget_twd_per_night": "每晚住宿預算",
        "total_budget_twd": "整趟總預算",
    }
    checks = {
        "departure_airport": structured.get("departure_airport"),
        "arrival_airport": structured.get("arrival_airport"),
        "start_date": structured.get("start_date"),
        "end_date": structured.get("end_date"),
        "travel_days": structured.get("travel_days"),
        "people": structured.get("people"),
        "flight_budget_twd_per_person": structured["flight_preferences"].get("flight_budget_twd_per_person"),
        "hotel_budget_twd_per_night": structured["hotel_preferences"].get("hotel_budget_twd_per_night"),
        "total_budget_twd": structured.get("total_budget_twd"),
    }
    return [labels[key] for key, value in checks.items() if value in [None, "", 0]]


def summary_text(structured):
    styles = "、".join(structured.get("travel_style") or []) or "未指定"
    flight = structured.get("flight_preferences") or {}
    hotel = structured.get("hotel_preferences") or {}
    return "\n".join([
        f"出發：{structured.get('departure_city')}（{structured.get('departure_airport')}）",
        f"目的地：{structured.get('destination_country')} {structured.get('destination_city')}（{structured.get('arrival_airport')}）",
        f"日期：{structured.get('start_date')} 至 {structured.get('end_date')}，{structured.get('travel_days')} 天 {structured.get('nights')} 晚",
        f"人數：{structured.get('people')} 人",
        f"航班：{flight.get('transfer_preference')}，每人機票預算 TWD {flight.get('flight_budget_twd_per_person')}",
        f"住宿：每晚 TWD {hotel.get('hotel_budget_twd_per_night')}",
        f"總預算：TWD {structured.get('total_budget_twd')}",
        f"行李：{structured.get('baggage')}",
        f"旅行風格：{styles}",
    ])


def _clean_json_text(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    if "{" in text and "}" in text:
        return text[text.find("{"):text.rfind("}") + 1]
    return text


def _gemini_api_key():
    if load_dotenv is not None:
        load_dotenv(dotenv_path=PROJECT_DIR / ".env", override=True)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("尚未設定 GEMINI_API_KEY。")
    return api_key


def _call_gemini_json(prompt: str) -> dict:
    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent",
        params={"key": _gemini_api_key()},
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.6,
                "responseMimeType": "application/json",
            },
        },
        timeout=60,
    )
    if response.status_code >= 400:
        try:
            message = response.json().get("error", {}).get("message") or response.text
        except ValueError:
            message = response.text
        raise RuntimeError(f"Gemini API 錯誤：{message}")
    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(_clean_json_text(text))


def _call_gemini_text(prompt: str) -> str:
    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent",
        params={"key": _gemini_api_key()},
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.5},
        },
        timeout=60,
    )
    if response.status_code >= 400:
        try:
            message = response.json().get("error", {}).get("message") or response.text
        except ValueError:
            message = response.text
        raise RuntimeError(f"Gemini API 錯誤：{message}")
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def build_attraction_user_profile(state):
    structured = state.get("structured_request", {}) or {}
    selected = state.get("selected", {}) or {}
    hotel = selected.get("hotel") or {}
    styles = structured.get("travel_style") or []
    if isinstance(styles, list):
        style_text = "、".join(str(item) for item in styles if item)
    else:
        style_text = str(styles or "")

    hotel_text = ""
    if hotel:
        hotel_text = f"；已選住宿：{hotel.get('title', '')} {hotel.get('detail', '')}"

    destination = " ".join(
        part
        for part in [
            structured.get("destination_country"),
            structured.get("destination_city"),
        ]
        if part
    ).strip()

    return {
        "departure": structured.get("departure_city") or "",
        "destination": destination,
        "days": structured.get("travel_days") or "",
        "budget": structured.get("total_budget_twd") or structured.get("budget_twd") or "",
        "style": f"{style_text}{hotel_text}",
    }


def normalize_attraction_options(attractions, destination):
    options = []
    for idx, item in enumerate((attractions or [])[:6], start=1):
        if not isinstance(item, dict):
            continue
        title = item.get("name") or item.get("title") or f"景點 {idx}"
        categories = item.get("categories") or []
        if isinstance(categories, list):
            categories_text = "、".join(str(category) for category in categories if category)
        else:
            categories_text = str(categories)

        lines = []
        if item.get("area"):
            lines.append(f"區域：{item.get('area')}")
        if categories_text:
            lines.append(f"類型：{categories_text}")
        if item.get("rating"):
            lines.append(f"評分參考：{item.get('rating')}")
        if item.get("duration"):
            lines.append(f"建議停留：{item.get('duration')}")
        if item.get("best_time"):
            lines.append(f"適合時段：{item.get('best_time')}")
        if item.get("description"):
            lines.append(str(item.get("description")))
        if item.get("detail"):
            lines.append(str(item.get("detail")))

        options.append({
            "id": idx,
            "title": title,
            "detail": "\n".join(lines),
            "reason": item.get("description") or "符合目的地、住宿位置與旅行風格。",
            "area": item.get("area") or "",
            "map_query": f"{destination} {title}".strip(),
            "image_url": item.get("image_url") or "",
            "raw": item,
        })
    return options


def generate_options(category, state):
    if category == "hotel":
        return recommend_hotel_options(state)
    if category == "activity":
        user_profile = build_attraction_user_profile(state)
        attractions = get_attractions(user_profile)
        return {
            "status": "success",
            "description": "以下是根據目的地、住宿位置與旅行風格產生的附近景點推薦：",
            "options": normalize_attraction_options(
                attractions,
                user_profile.get("destination") or "",
            ),
        }

    selected = state.get("selected", {})
    structured = state.get("structured_request", {})
    category_names = {
        "hotel": "住宿",
        "activity": "附近景點",
        "restaurant": "周邊美食",
    }
    rules = {
        "hotel": "推薦 3 個真實住宿區域或飯店。必須符合目的地、每晚住宿預算、人數、晚數、房型、是否近車站與偏好區域。title 必須是可用 Google Maps 搜尋的真實飯店名稱或明確住宿區域；detail 必須包含區域、特色、預估每晚價格、適合原因與注意事項。請額外提供 reason、area、estimated_price_twd、map_query。",
        "activity": "根據已選住宿與目的地推薦 3 個附近景點或體驗，不要推薦餐廳。title 必須可用 Google Maps 搜尋，detail 包含地區、適合原因、預估停留時間。",
        "restaurant": "根據已選景點推薦 3 個周邊餐廳或在地美食。title 必須是餐廳名稱，detail 包含特色菜、預估價格、距離或區域、是否需訂位。",
    }
    prompt = f"""
請用繁體中文產生 {category_names.get(category, category)} 選項。

請只輸出 JSON，不要 Markdown。
格式：
{{
  "description": "一句給使用者看的說明",
  "options": [
    {{"id": 1, "title": "名稱", "detail": "說明", "reason": "推薦理由", "area": "區域", "estimated_price_twd": 4000, "map_query": "Google Maps 搜尋字串"}},
    {{"id": 2, "title": "名稱", "detail": "說明", "reason": "推薦理由", "area": "區域", "estimated_price_twd": 4000, "map_query": "Google Maps 搜尋字串"}},
    {{"id": 3, "title": "名稱", "detail": "說明", "reason": "推薦理由", "area": "區域", "estimated_price_twd": 4000, "map_query": "Google Maps 搜尋字串"}}
  ]
}}

規則：
{rules.get(category, "")}
不可固定輸出日本或東京，必須符合 structured_request 的目的地。
如果是 hotel，請把「已選航班」的抵達時間、住宿預算與左側住宿偏好都納入判斷；但請提醒使用者實際價格與空房仍需到訂房平台確認。

structured_request:
{json.dumps(structured, ensure_ascii=False, indent=2)}

已選項目：
{json.dumps(selected, ensure_ascii=False, indent=2)}
""".strip()
    payload = _call_gemini_json(prompt)
    return {
        "status": "success",
        "description": payload.get("description", "請選擇以下選項。"),
        "options": payload.get("options", []),
    }


def generate_itinerary(state):
    prompt = f"""
請根據以下資料產生完整自由行行程建議，使用繁體中文。

請只輸出 JSON，不要 Markdown，不要使用 *、**、###、表格語法或分隔線。
語氣要簡潔、清楚、像旅遊規劃平台的結果頁，不要寫成長篇文章。

JSON 格式必須如下：
{{
  "title": "行程標題",
  "subtitle": "一句話總結這趟旅程",
  "summary": ["重點 1", "重點 2", "重點 3"],
  "selected_plan": [
    {{"label": "航班", "value": "已選航班摘要"}},
    {{"label": "住宿", "value": "已選住宿摘要"}},
    {{"label": "景點", "value": "已選景點摘要"}},
    {{"label": "美食", "value": "已選餐廳摘要"}}
  ],
  "days": [
    {{
      "day": "Day 1",
      "date": "YYYY-MM-DD",
      "title": "當日主題",
      "items": [
        {{"time": "上午", "place": "地點或活動", "note": "簡短安排說明"}},
        {{"time": "下午", "place": "地點或活動", "note": "簡短安排說明"}},
        {{"time": "晚上", "place": "地點或活動", "note": "簡短安排說明"}}
      ]
    }}
  ],
  "budget_notes": ["預算提醒 1", "預算提醒 2"],
  "transport_tips": ["交通提醒 1", "交通提醒 2"],
  "risk_tips": ["風險提醒 1", "風險提醒 2"]
}}

規則：
- 每個陣列最多 5 筆，避免內容過長。
- 每個 note 以 35 個中文字內為原則。
- 每日行程要照航班、住宿、景點、餐廳的選擇銜接。
- 如果預算看起來不足，請在 budget_notes 清楚提醒。
- 不要新增使用者沒有選過的主要景點或餐廳；若需要補空檔，只能用「飯店周邊自由活動」這類彈性安排。

資料：
{json.dumps(state, ensure_ascii=False, indent=2)}
""".strip()
    payload = _call_gemini_json(prompt)
    return {"status": "success", "itinerary": payload}


HTML = r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI 協作式旅遊規劃平台</title>
  <style>
    :root {
      --sidebar: #f3f5fa;
      --surface: #ffffff;
      --line: #dfe5ee;
      --text: #171717;
      --muted: #667085;
      --blue: #2f80ed;
      --blue-soft: #e8f2ff;
      --green: #16a34a;
      --dark: #111827;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft JhengHei", system-ui, sans-serif;
      color: var(--text);
      background: var(--surface);
    }
    .app { min-height: 100vh; display: grid; grid-template-columns: 380px 1fr; }
    aside {
      background: var(--sidebar);
      padding: 34px 30px;
      overflow-y: auto;
      height: 100vh;
      border-right: 1px solid var(--line);
    }
    main { padding: 52px 56px; overflow-y: auto; height: 100vh; }
    h1 { font-size: 44px; line-height: 1.1; margin: 0 0 30px; }
    h2 { font-size: 30px; margin: 0 0 20px; }
    h3 { margin: 0 0 14px; }
    label { display: block; font-size: 14px; margin: 15px 0 7px; }
    input, select, textarea {
      width: 100%;
      border: 1px solid transparent;
      background: #fff;
      color: var(--text);
      padding: 12px 13px;
      font: inherit;
      outline: none;
    }
    input:focus, select:focus, textarea:focus { border-color: var(--blue); }
    textarea { min-height: 118px; resize: vertical; }
    .row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .date-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .go {
      margin-top: 22px;
      width: 100%;
      border: 0;
      background: var(--dark);
      color: white;
      font: inherit;
      font-weight: 700;
      padding: 14px;
      cursor: pointer;
    }
    .go:disabled { opacity: .55; cursor: wait; }
    .tabs {
      display: flex;
      gap: 0;
      border-bottom: 2px solid var(--line);
      margin-bottom: 28px;
    }
    .tab {
      border: 1px solid #aaa;
      border-bottom: 0;
      background: #fff;
      padding: 12px 24px;
      cursor: pointer;
      color: var(--text);
      font: inherit;
    }
    .tab.active { color: var(--blue); border-top-color: var(--blue); }
    .panel {
      display: none;
      min-height: 370px;
      border: 1px solid #aaa;
      border-top: 0;
      padding: 34px 8px 30px;
    }
    .panel.active { display: block; }
    .notice {
      background: var(--blue-soft);
      color: #0f4c81;
      padding: 18px 22px;
      margin: 8px 0 18px;
      line-height: 1.7;
      white-space: pre-wrap;
    }
    .cards { display: grid; gap: 14px; }
    .card {
      border: 1px solid var(--line);
      background: #fff;
      padding: 16px;
      cursor: pointer;
      transition: border-color .15s, box-shadow .15s;
    }
    .card:hover {
      border-color: var(--blue);
      box-shadow: 0 8px 24px rgba(15, 23, 42, .08);
    }
    .card.selected { border-color: var(--green); background: #f0fdf4; }
    .card.multi::before {
      content: "□";
      float: right;
      color: var(--muted);
      font-weight: 800;
      font-size: 20px;
    }
    .card.multi.selected::before {
      content: "✓";
      color: var(--green);
    }
    .card-title { font-weight: 800; margin-bottom: 7px; }
    .card-detail { color: #344054; line-height: 1.65; white-space: pre-wrap; }
    .card-meta { margin-top: 10px; color: #475467; font-size: 14px; line-height: 1.6; }
    .map-link {
      display: inline-block;
      margin-top: 12px;
      color: var(--blue);
      text-decoration: none;
      font-weight: 700;
    }
    .map-link:hover { text-decoration: underline; }
    .status { color: var(--muted); margin: 12px 0; line-height: 1.7; }
    .error { background: #fff1f2; color: #be123c; padding: 16px; line-height: 1.7; white-space: pre-wrap; }
    .summary { margin-top: 18px; color: var(--muted); font-size: 14px; white-space: pre-wrap; }
    .loader { color: var(--blue); padding: 18px 0; }
    .side-section {
      border-top: 1px solid var(--line);
      margin-top: 22px;
      padding-top: 18px;
    }
    .side-section h3 { font-size: 18px; margin: 0 0 8px; }
    .secondary {
      border: 1px solid var(--dark);
      background: #fff;
      color: var(--dark);
      font: inherit;
      font-weight: 700;
      padding: 12px 16px;
      cursor: pointer;
    }
    .action-row {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 18px;
    }
    .itinerary-layout {
      display: grid;
      gap: 16px;
      margin-top: 8px;
    }
    .itinerary-hero {
      background: #f8fafc;
      border: 1px solid var(--line);
      padding: 20px 22px;
    }
    .itinerary-hero h3 {
      font-size: 24px;
      margin: 0 0 8px;
    }
    .itinerary-hero p {
      margin: 0;
      color: var(--muted);
      line-height: 1.7;
    }
    .itinerary-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .info-block {
      border: 1px solid var(--line);
      background: #fff;
      padding: 16px;
    }
    .info-block h3 {
      font-size: 18px;
      margin: 0 0 12px;
    }
    .info-list {
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .info-list li {
      color: #344054;
      line-height: 1.65;
    }
    .selected-row {
      display: grid;
      grid-template-columns: 84px 1fr;
      gap: 10px;
      padding: 8px 0;
      border-top: 1px solid #eef2f7;
      line-height: 1.6;
    }
    .selected-row:first-child { border-top: 0; }
    .selected-label {
      color: var(--muted);
      font-weight: 700;
    }
    .day-card {
      border: 1px solid var(--line);
      background: #fff;
      padding: 16px;
    }
    .day-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 12px;
    }
    .day-head h3 {
      font-size: 18px;
      margin: 0;
    }
    .day-date {
      color: var(--muted);
      font-size: 14px;
      white-space: nowrap;
    }
    .timeline {
      display: grid;
      gap: 10px;
    }
    .timeline-item {
      display: grid;
      grid-template-columns: 76px 1fr;
      gap: 12px;
      border-top: 1px solid #eef2f7;
      padding-top: 10px;
    }
    .timeline-item:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .time-chip {
      color: #0f4c81;
      font-weight: 800;
    }
    .place {
      font-weight: 800;
      margin-bottom: 4px;
    }
    .note {
      color: #475467;
      line-height: 1.65;
    }
    @media (max-width: 960px) {
      .app { grid-template-columns: 1fr; }
      aside, main { height: auto; }
      h1 { font-size: 34px; }
      .itinerary-grid { grid-template-columns: 1fr; }
      .timeline-item { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <h2>旅遊基本資料</h2>
      <label>出發地</label>
      <select id="departure_city">
        <option>台北</option><option>桃園</option><option>台中</option><option>高雄</option>
      </select>
      <label>目的國家</label>
      <select id="destination_country"></select>
      <label>目的城市</label>
      <select id="destination_city"></select>
      <div class="date-row">
        <div><label>出發日</label><input id="start_date" type="date" value="2026-06-15"></div>
        <div><label>回程日</label><input id="end_date" type="date" value="2026-06-20"></div>
      </div>
      <div class="row">
        <div><label>天數</label><input id="travel_days" type="number" min="1" value="5"></div>
        <div><label>晚數</label><input id="nights" type="number" min="0" value="4"></div>
        <div><label>人數</label><input id="people" type="number" min="1" value="4"></div>
      </div>
      <label>直飛 / 轉機</label>
      <select id="transfer_preference">
        <option>只要直飛</option>
        <option>可轉機一次</option>
        <option>可轉機兩次以上</option>
        <option>不限</option>
      </select>
      <label>每人機票預算 TWD</label>
      <input id="flight_budget_twd_per_person" type="number" value="8000">
      <label>每晚住宿預算 TWD</label>
      <input id="hotel_budget_twd_per_night" type="number" value="4000">
      <div class="side-section">
        <h3>住宿偏好</h3>
        <label>偏好區域</label>
        <select id="preferred_area">
          <option>不限</option>
          <option>市中心</option>
          <option>車站附近</option>
          <option>商圈附近</option>
          <option>海邊 / 度假區</option>
          <option>安靜住宅區</option>
          <option>親子友善區域</option>
        </select>
        <label>房型需求</label>
        <select id="room_type">
          <option>未指定</option>
          <option>雙人房</option>
          <option>三人房</option>
          <option>四人房</option>
          <option>家庭房</option>
          <option>兩間雙人房</option>
        </select>
        <label>是否希望近車站 / 交通節點</label>
        <select id="near_station">
          <option value="true" selected>希望近車站或交通方便</option>
          <option value="false">不一定要近車站</option>
        </select>
        <label>住宿備註</label>
        <textarea id="hotel_notes" placeholder="例如：希望有早餐、附近要有便利商店、不要太吵、可接受公寓式飯店。"></textarea>
      </div>
      <label>整趟總預算 TWD</label>
      <input id="total_budget_twd" type="number" value="80000">
      <label>行李</label>
      <select id="baggage">
        <option>無托運</option>
        <option selected>每人 1 件托運</option>
        <option>每人 2 件托運</option>
        <option>依航空公司規定</option>
      </select>
      <label>旅行風格</label>
      <textarea id="travel_style">美食、購物、拍照，不要太趕</textarea>
      <button class="go" id="goBtn" onclick="startSearch()">GO!</button>
      <div class="summary" id="summary"></div>
    </aside>
    <main>
      <h1>AI 協作式旅遊規劃平台</h1>
      <div class="tabs">
        <button class="tab active" data-tab="flight">航班</button>
        <button class="tab" data-tab="hotel">住宿</button>
        <button class="tab" data-tab="activity">附近景點</button>
        <button class="tab" data-tab="restaurant">周邊美食</button>
        <button class="tab" data-tab="itinerary">行程建議</button>
      </div>
      <section class="panel active" id="flight"><h2>航班推薦</h2><div class="notice">這裡之後會接 modules 裡的 flight recommender。</div></section>
      <section class="panel" id="hotel"><h2>住宿推薦</h2><div class="notice">請先選擇航班，系統會依目的地與住宿預算推薦住宿。</div></section>
      <section class="panel" id="activity"><h2>附近景點</h2><div class="notice">請先選擇住宿，系統會依住宿位置推薦附近景點。</div></section>
      <section class="panel" id="restaurant"><h2>周邊美食</h2><div class="notice">請先選擇景點，系統會推薦景點周邊美食。</div></section>
      <section class="panel" id="itinerary"><h2>行程建議</h2><div class="notice">選完航班、住宿、景點與餐廳後，會產生完整行程。</div></section>
    </main>
  </div>
  <script>
    const countryCities = __COUNTRY_CITIES__;
    const state = { structured_request: null, selected: {} };

    function $(id) { return document.getElementById(id); }
    function setTab(name) {
      document.querySelectorAll('.tab').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === name));
      document.querySelectorAll('.panel').forEach(panel => panel.classList.toggle('active', panel.id === name));
    }
    document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => setTab(btn.dataset.tab)));
    ['start_date', 'end_date'].forEach(id => {
      const el = $(id);
      if (el) el.addEventListener('change', updateTripLengthFromDates);
    });

    function initCountries() {
      const country = $('destination_country');
      country.innerHTML = Object.keys(countryCities).map(name => `<option>${name}</option>`).join('');
      country.value = '日本';
      updateCities();
      $('destination_city').value = '沖繩';
      country.addEventListener('change', updateCities);
    }
    function updateCities() {
      const cities = countryCities[$('destination_country').value] || [];
      $('destination_city').innerHTML = cities.map(name => `<option>${name}</option>`).join('');
    }
    initCountries();

    function updateTripLengthFromDates() {
      const start = $('start_date').value;
      const end = $('end_date').value;
      if (!start || !end) return;
      const startDate = new Date(`${start}T00:00:00`);
      const endDate = new Date(`${end}T00:00:00`);
      if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return;
      const diffDays = Math.round((endDate - startDate) / 86400000);
      if (diffDays < 0) {
        $('travel_days').value = '';
        $('nights').value = '';
        return;
      }
      $('travel_days').value = diffDays + 1;
      $('nights').value = diffDays;
    }
    updateTripLengthFromDates();

    function formData() {
      const ids = [
        'departure_city', 'destination_country', 'destination_city', 'start_date', 'end_date',
        'travel_days', 'nights', 'people', 'transfer_preference', 'flight_budget_twd_per_person',
        'hotel_budget_twd_per_night', 'preferred_area', 'room_type', 'near_station', 'hotel_notes',
        'total_budget_twd', 'baggage', 'travel_style'
      ];
      return Object.fromEntries(ids.map(id => [id, $(id).value]));
    }
    function enrichStateFromSidebar() {
      if (!state.structured_request) return;
      const data = formData();
      state.structured_request.hotel_preferences = {
        ...(state.structured_request.hotel_preferences || {}),
        preferred_area: data.preferred_area === '不限' ? null : data.preferred_area,
        room_type: data.room_type === '未指定' ? null : data.room_type,
        near_station: data.near_station === 'true',
        hotel_budget_twd_per_night: Number(data.hotel_budget_twd_per_night || 0),
        hotel_budget_twd_total: Number(data.hotel_budget_twd_per_night || 0) * Number(data.nights || 0)
      };
      state.structured_request.special_notes = data.hotel_notes || state.structured_request.special_notes || null;
    }
    function setLoading(tab, text) {
      $(tab).innerHTML = `<h2>${heading(tab)}</h2><div class="loader">${text}</div>`;
      setTab(tab);
    }
    function heading(tab) {
      return { flight: '航班推薦', hotel: '住宿推薦', activity: '附近景點', restaurant: '周邊美食', itinerary: '行程建議' }[tab];
    }
    function showError(tab, message) {
      $(tab).innerHTML = `<h2>${heading(tab)}</h2><div class="error">${escapeHtml(message)}</div>`;
      setTab(tab);
    }
    function escapeHtml(text) {
      return String(text ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
    }
    function googleMapUrl(item) {
      const destination = `${state.structured_request?.destination_country || ''} ${state.structured_request?.destination_city || ''}`.trim();
      const query = item.map_query || `${item.title || ''} ${destination}`;
      return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
    }
    function isMultiSelectTab(tab) {
      return tab === 'activity' || tab === 'restaurant';
    }
    async function postJSON(url, data) {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      return await res.json();
    }
    async function startSearch() {
      $('goBtn').disabled = true;
      state.selected = {};
      setLoading('flight', '正在整理表單資料並查詢航班...');
      try {
        const result = await postJSON('/api/search', formData());
        if (result.status !== 'success') {
          showError('flight', result.message || '查詢失敗');
          return;
        }
        state.structured_request = result.structured_request;
        $('summary').textContent = result.summary || '';
        renderOptions('flight', result.flight.description || '以下是符合條件的航班推薦：', result.flight.options || []);
      } catch (err) {
        showError('flight', err.message);
      } finally {
        $('goBtn').disabled = false;
      }
    }
    function renderOptions(tab, description, options) {
      const cards = options.map((item, index) => `
        <div class="card ${isMultiSelectTab(tab) ? 'multi' : ''}" onclick="selectOption('${tab}', ${index})">
          <div class="card-title">${escapeHtml(item.title || `選項 ${index + 1}`)}</div>
          <div class="card-detail">${escapeHtml(item.detail || '')}</div>
          ${item.reason ? `<div class="card-meta"><strong>推薦理由：</strong>${escapeHtml(item.reason)}</div>` : ''}
          ${item.area || item.estimated_price_twd ? `<div class="card-meta">${item.area ? `區域：${escapeHtml(item.area)}` : ''}${item.area && item.estimated_price_twd ? ' ｜ ' : ''}${item.estimated_price_twd ? `預估每晚：TWD ${escapeHtml(item.estimated_price_twd)}` : ''}</div>` : ''}
          ${tab === 'hotel' ? `<a class="map-link" href="${googleMapUrl(item)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">開啟 Google Maps</a>` : ''}
        </div>
      `).join('');
      const multiAction = isMultiSelectTab(tab)
        ? `<div class="action-row"><button class="secondary" onclick="confirmMultiSelection('${tab}')">${tab === 'activity' ? '確認景點，前往美食推薦' : '確認美食，產生行程'}</button></div>`
        : '';
      $(tab).innerHTML = `<h2>${heading(tab)}</h2><div class="notice">${escapeHtml(description)}${isMultiSelectTab(tab) ? '\n可複選多個項目。' : ''}</div><div class="cards">${cards || '<div class="status">目前沒有可選項目。</div>'}</div>${multiAction}`;
      $(tab)._options = options;
      $(tab)._selectedIndexes = new Set();
      setTab(tab);
    }
    function cleanItineraryText(text) {
      return String(text || '')
        .replace(/\*\*/g, '')
        .replace(/^\s*[*-]\s+/gm, '')
        .replace(/^#{1,6}\s*/gm, '')
        .replace(/^\s*-{3,}\s*$/gm, '')
        .trim();
    }
    function renderList(items) {
      const list = Array.isArray(items) ? items : [];
      if (!list.length) return '<div class="status">目前沒有補充資料。</div>';
      return `<ul class="info-list">${list.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
    }
    function renderInfoBlock(title, items) {
      return `<section class="info-block"><h3>${escapeHtml(title)}</h3>${renderList(items)}</section>`;
    }
    function renderSelectedPlan(items) {
      const rows = Array.isArray(items) ? items : [];
      if (!rows.length) return renderInfoBlock('已選方案', []);
      return `
        <section class="info-block">
          <h3>已選方案</h3>
          ${rows.map(item => `
            <div class="selected-row">
              <div class="selected-label">${escapeHtml(item.label || '')}</div>
              <div>${escapeHtml(item.value || '')}</div>
            </div>
          `).join('')}
        </section>
      `;
    }
    function renderDay(day, index) {
      const items = Array.isArray(day?.items) ? day.items : [];
      return `
        <section class="day-card">
          <div class="day-head">
            <h3>${escapeHtml(day?.day || `Day ${index + 1}`)}｜${escapeHtml(day?.title || '彈性行程')}</h3>
            <div class="day-date">${escapeHtml(day?.date || '')}</div>
          </div>
          <div class="timeline">
            ${items.map(item => `
              <div class="timeline-item">
                <div class="time-chip">${escapeHtml(item.time || '')}</div>
                <div>
                  <div class="place">${escapeHtml(item.place || '')}</div>
                  <div class="note">${escapeHtml(item.note || '')}</div>
                </div>
              </div>
            `).join('') || '<div class="status">這天保留彈性活動。</div>'}
          </div>
        </section>
      `;
    }
    function renderItinerary(data) {
      if (!data || typeof data === 'string') {
        const text = cleanItineraryText(data);
        $('itinerary').innerHTML = `
          <h2>行程建議</h2>
          <div class="itinerary-layout">
            <section class="itinerary-hero">
              <h3>完整行程建議</h3>
              <p>${escapeHtml(text || '目前沒有行程內容。')}</p>
            </section>
          </div>
        `;
        setTab('itinerary');
        return;
      }
      const days = Array.isArray(data.days) ? data.days : [];
      $('itinerary').innerHTML = `
        <h2>行程建議</h2>
        <div class="itinerary-layout">
          <section class="itinerary-hero">
            <h3>${escapeHtml(data.title || '完整行程建議')}</h3>
            <p>${escapeHtml(data.subtitle || '以下依照你選定的航班、住宿、景點與美食安排。')}</p>
          </section>
          <div class="itinerary-grid">
            ${renderInfoBlock('需求摘要', data.summary)}
            ${renderSelectedPlan(data.selected_plan)}
          </div>
          <section class="info-block">
            <h3>每日行程</h3>
            <div class="itinerary-layout">${days.map(renderDay).join('') || '<div class="status">目前沒有每日行程。</div>'}</div>
          </section>
          <div class="itinerary-grid">
            ${renderInfoBlock('預算提醒', data.budget_notes)}
            ${renderInfoBlock('交通提醒', data.transport_tips)}
            ${renderInfoBlock('風險提醒', data.risk_tips)}
          </div>
        </div>
      `;
      setTab('itinerary');
    }
    async function selectOption(tab, index) {
      const options = $(tab)._options || [];
      const selected = options[index];
      if (!selected) return;
      if (isMultiSelectTab(tab)) {
        const selectedIndexes = $(tab)._selectedIndexes || new Set();
        if (selectedIndexes.has(index)) selectedIndexes.delete(index);
        else selectedIndexes.add(index);
        $(tab)._selectedIndexes = selectedIndexes;
        document.querySelectorAll(`#${tab} .card`).forEach((card, i) => card.classList.toggle('selected', selectedIndexes.has(i)));
        state.selected[tab] = Array.from(selectedIndexes).map(i => options[i]);
        return;
      }
      state.selected[tab] = selected;
      document.querySelectorAll(`#${tab} .card`).forEach((card, i) => card.classList.toggle('selected', i === index));
      if (tab === 'flight') return showHotelPreferenceStep();
      if (tab === 'hotel') return loadOptions('activity');
    }
    function confirmMultiSelection(tab) {
      const selectedItems = state.selected[tab] || [];
      if (!Array.isArray(selectedItems) || selectedItems.length === 0) {
        alert(tab === 'activity' ? '請至少選擇一個景點。' : '請至少選擇一個美食或餐廳。');
        return;
      }
      if (tab === 'activity') return loadOptions('restaurant');
      if (tab === 'restaurant') return loadItinerary();
    }
    function showHotelPreferenceStep() {
      const budget = $('hotel_budget_twd_per_night').value || state.structured_request?.hotel_preferences?.hotel_budget_twd_per_night || '';
      $('hotel').innerHTML = `
        <h2>住宿推薦</h2>
        <div class="notice">已選定航班。請在左側確認住宿偏好，例如偏好區域、房型、是否近車站與備註。系統會使用每晚住宿預算 TWD ${escapeHtml(budget)} 來產生住宿推薦。</div>
        <button class="secondary" onclick="loadOptions('hotel')">產生住宿推薦</button>
      `;
      setTab('hotel');
    }
    async function loadOptions(category) {
      enrichStateFromSidebar();
      setLoading(category, `正在產生${heading(category)}...`);
      try {
        const result = await postJSON('/api/options', { category, state });
        if (result.status !== 'success') {
          showError(category, result.message || '產生選項失敗');
          return;
        }
        renderOptions(category, result.description, result.options || []);
      } catch (err) {
        showError(category, err.message);
      }
    }
    async function loadItinerary() {
      setLoading('itinerary', '正在產生完整行程建議...');
      try {
        const result = await postJSON('/api/itinerary', { state });
        if (result.status !== 'success') {
          showError('itinerary', result.message || '產生行程失敗');
          return;
        }
        renderItinerary(result.itinerary);
      } catch (err) {
        showError('itinerary', err.message);
      }
    }
  </script>
</body>
</html>""".replace("__COUNTRY_CITIES__", json.dumps(COUNTRY_CITIES, ensure_ascii=False))


class TravelPlannerHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[web] {self.address_string()} - {fmt % args}")

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path != "/":
            self.send_error(404)
            return
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            data = self._read_json()
            if path == "/api/search":
                structured = build_structured_request(data)
                missing = missing_fields(structured)
                if missing:
                    self._send_json({
                        "status": "need_more_info",
                        "message": "請補齊或調整以下欄位：\n- " + "\n- ".join(missing),
                        "structured_request": structured,
                        "summary": summary_text(structured),
                    })
                    return
                flight = recommend_flight_options(structured)
                if flight.get("status") != "success":
                    self._send_json({
                        "status": "error",
                        "message": flight.get("message", "航班查詢失敗。"),
                        "structured_request": structured,
                        "summary": summary_text(structured),
                    })
                    return
                self._send_json({
                    "status": "success",
                    "structured_request": structured,
                    "summary": summary_text(structured),
                    "flight": {
                        "description": "以下是根據你的日期、機場與預算查到的航班推薦：",
                        "options": flight.get("options", []),
                    },
                })
                return
            if path == "/api/options":
                self._send_json(generate_options(data.get("category"), data.get("state", {})))
                return
            if path == "/api/itinerary":
                self._send_json(generate_itinerary(data.get("state", {})))
                return
            self.send_error(404)
        except Exception as exc:
            self._send_json({"status": "error", "message": str(exc)}, status=500)


def run(host="127.0.0.1", port=7860, open_browser=True):
    server = ThreadingHTTPServer((host, port), TravelPlannerHandler)
    url = f"http://{host}:{port}"
    print(f"AI 協作式旅遊規劃平台已啟動：{url}")
    if open_browser:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    run()
