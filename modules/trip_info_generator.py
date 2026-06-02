import json
import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None


MODULE_NAME = "trip_info_generator"


def _empty_structured_request() -> dict:
    return {
        "departure_city": None,
        "departure_airport": None,
        "destination_country": None,
        "destination_city": None,
        "arrival_airport": None,
        "start_date": None,
        "start_date_text": None,
        "end_date": None,
        "travel_days": None,
        "nights": None,
        "people": None,
        "budget_twd": None,
        "total_budget_twd": None,
        "budget_level": None,
        "travel_style": [],
        "preferred_pace": None,
        "baggage": None,
        "flight_preferences": {
            "prefer_direct": None,
            "transfer_preference": None,
            "preferred_departure_time": None,
            "max_transfer_count": None,
            "flight_budget_twd_per_person": None,
        },
        "hotel_preferences": {
            "preferred_area": None,
            "room_type": None,
            "near_station": None,
            "hotel_budget_twd_per_night": None,
            "hotel_budget_twd_total": None,
        },
        "food_preferences": {
            "favorite_types": [],
            "avoid_types": [],
        },
        "special_notes": None,
    }


def _result(status: str, structured_request=None, missing_fields=None, message="") -> dict:
    result = {
        "module": MODULE_NAME,
        "status": status,
        "structured_request": structured_request or {},
        "missing_fields": missing_fields or [],
    }
    if message:
        result["message"] = message
    return result


def _clean_json_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    if "{" in text and "}" in text:
        text = text[text.find("{"):text.rfind("}") + 1]
    return text.strip()


def _normalize_structured_request(data: dict) -> dict:
    structured = _empty_structured_request()
    if not isinstance(data, dict):
        return structured

    for key in structured:
        if key in data:
            structured[key] = data[key]

    for nested_key in ["flight_preferences", "hotel_preferences", "food_preferences"]:
        if not isinstance(structured.get(nested_key), dict):
            structured[nested_key] = _empty_structured_request()[nested_key]
            continue
        defaults = _empty_structured_request()[nested_key]
        for key, value in defaults.items():
            structured[nested_key].setdefault(key, value)

    if not isinstance(structured.get("travel_style"), list):
        structured["travel_style"] = []

    if structured.get("total_budget_twd") is None and structured.get("budget_twd") is not None:
        structured["total_budget_twd"] = structured.get("budget_twd")
    if structured.get("budget_twd") is None and structured.get("total_budget_twd") is not None:
        structured["budget_twd"] = structured.get("total_budget_twd")

    _fill_airport_codes(structured)
    return structured


def _fill_airport_codes(structured_request: dict) -> None:
    airport_map = {
        "台北": "TPE",
        "臺北": "TPE",
        "桃園": "TPE",
        "高雄": "KHH",
        "台中": "RMQ",
        "臺中": "RMQ",
        "東京": "NRT",
        "大阪": "KIX",
        "首爾": "ICN",
        "曼谷": "BKK",
        "新加坡": "SIN",
        "香港": "HKG",
        "澳門": "MFM",
        "河內": "HAN",
        "胡志明": "SGN",
        "峴港": "DAD",
        "富國島": "PQC",
        "峇里島": "DPS",
        "巴里島": "DPS",
        "登巴薩": "DPS",
        "雅加達": "CGK",
        "吉隆坡": "KUL",
        "檳城": "PEN",
        "馬尼拉": "MNL",
        "宿霧": "CEB",
        "洛杉磯": "LAX",
        "紐約": "JFK",
        "倫敦": "LHR",
        "巴黎": "CDG",
    }

    departure_city = str(structured_request.get("departure_city") or "")
    destination_city = str(structured_request.get("destination_city") or "")

    if not structured_request.get("departure_airport"):
        for city, code in airport_map.items():
            if city in departure_city:
                structured_request["departure_airport"] = code
                break

    if not structured_request.get("arrival_airport"):
        for city, code in airport_map.items():
            if city in destination_city:
                structured_request["arrival_airport"] = code
                break


def _find_missing_fields(structured_request: dict) -> list[str]:
    required_fields = [
        "departure_city",
        "departure_airport",
        "destination_country",
        "destination_city",
        "arrival_airport",
        "travel_days",
        "nights",
        "people",
        "budget_twd",
        "travel_style",
        "baggage",
    ]
    missing = []

    for field in required_fields:
        value = structured_request.get(field)
        if value is None or value == "" or value == []:
            missing.append(field)

    if not structured_request.get("start_date") and not structured_request.get("start_date_text"):
        missing.append("start_date")

    flight_preferences = structured_request.get("flight_preferences") or {}
    if flight_preferences.get("prefer_direct") is None and flight_preferences.get("max_transfer_count") is None:
        missing.append("flight_transfer_preference")
    if not flight_preferences.get("flight_budget_twd_per_person"):
        missing.append("flight_budget_twd_per_person")

    hotel_preferences = structured_request.get("hotel_preferences") or {}
    if not hotel_preferences.get("hotel_budget_twd_per_night") and not hotel_preferences.get("hotel_budget_twd_total"):
        missing.append("hotel_budget")

    if not structured_request.get("total_budget_twd") and not structured_request.get("budget_twd"):
        missing.append("total_budget_twd")

    return missing

def _build_prompt(request: dict) -> str:
    return f"""
You are a travel requirement structuring assistant. Convert the user's free-form travel request into the fixed JSON format below.

Rules:
1. Return JSON only. Do not return Markdown or code fences.
2. If information is unclear, use null or an empty array.
3. Convert all money amounts to integer TWD.
4. If the user says per-person flight budget, fill flight_preferences.flight_budget_twd_per_person.
5. If the user says hotel budget per night, fill hotel_preferences.hotel_budget_twd_per_night. If the user says total hotel budget, fill hotel_preferences.hotel_budget_twd_total.
6. If the user says total trip budget, fill both budget_twd and total_budget_twd.
7. Flight transfer preference: direct only => prefer_direct=true and max_transfer_count=0; one transfer allowed => prefer_direct=false and max_transfer_count=1; no preference => prefer_direct=false and max_transfer_count=null.
8. If date has no clear year or exact date, keep start_date/end_date as null and put the original text in start_date_text.
9. If enough information is available, status="success". If anything required is missing, status="need_more_info".
10. missing_fields must list missing field names. message must be short Traditional Chinese.
11. Convert departure_airport and arrival_airport to IATA airport codes when possible, e.g. Taipei=TPE, Tokyo=NRT, Phu Quoc=PQC, Bali/DPS.

Required information:
- departure_city
- departure_airport
- destination_country
- destination_city
- arrival_airport
- start_date or start_date_text
- travel_days
- nights
- people
- budget_twd / total_budget_twd
- flight_preferences.flight_budget_twd_per_person
- flight_preferences.prefer_direct or flight_preferences.max_transfer_count
- hotel_preferences.hotel_budget_twd_per_night or hotel_preferences.hotel_budget_twd_total
- travel_style
- baggage

Return exactly this JSON shape:
{{
  "module": "trip_info_generator",
  "status": "success or need_more_info",
  "structured_request": {{
    "departure_city": null,
    "departure_airport": null,
    "destination_country": null,
    "destination_city": null,
    "arrival_airport": null,
    "start_date": null,
    "start_date_text": null,
    "end_date": null,
    "travel_days": null,
    "nights": null,
    "people": null,
    "budget_twd": null,
    "total_budget_twd": null,
    "budget_level": null,
    "travel_style": [],
    "preferred_pace": null,
    "baggage": null,
    "flight_preferences": {{
      "prefer_direct": null,
      "transfer_preference": null,
      "preferred_departure_time": null,
      "max_transfer_count": null,
      "flight_budget_twd_per_person": null
    }},
    "hotel_preferences": {{
      "preferred_area": null,
      "room_type": null,
      "near_station": null,
      "hotel_budget_twd_per_night": null,
      "hotel_budget_twd_total": null
    }},
    "food_preferences": {{
      "favorite_types": [],
      "avoid_types": []
    }},
    "special_notes": null
  }},
  "missing_fields": [],
  "message": ""
}}

User input:
{json.dumps(request, ensure_ascii=False, indent=2)}
""".strip()

def run(request: dict) -> dict:
    if load_dotenv is None:
        return _result(
            "error",
            message="尚未安裝 python-dotenv，請先執行 pip install python-dotenv。",
        )

    if genai is None or types is None:
        return _result(
            "error",
            message="尚未安裝 google-genai，請先執行 pip install google-genai。",
        )

    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(dotenv_path=env_path, override=True)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return _result(
            "error",
            message="找不到 GEMINI_API_KEY，請確認 .env 是否設定正確。",
        )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=_build_prompt(request),
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )

        payload = json.loads(_clean_json_text(response.text))
        structured_request = _normalize_structured_request(
            payload.get("structured_request", {})
        )
        status = payload.get("status", "success")
        if status not in ["success", "need_more_info"]:
            status = "success"

        missing_fields = list(dict.fromkeys(
            (payload.get("missing_fields") or []) + _find_missing_fields(structured_request)
        ))
        if missing_fields:
            status = "need_more_info"

        message = (
            "還需要補充：" + "、".join(missing_fields)
            if missing_fields
            else payload.get("message", "")
        )

        return _result(
            status,
            structured_request=structured_request,
            missing_fields=missing_fields,
            message=message,
        )
    except json.JSONDecodeError as e:
        return _result("error", message=f"Gemini 回傳內容不是有效 JSON：{e}")
    except Exception as e:
        return _result("error", message=str(e))
