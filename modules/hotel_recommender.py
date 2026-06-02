# -*- coding: utf-8 -*-
import json
import os
import re
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


MODULE_NAME = "hotel_recommender"
MODEL_NAME = "gemini-2.5-flash-lite"


def _result(status: str, options=None, description="", message="") -> dict:
    result = {
        "module": MODULE_NAME,
        "status": status,
        "description": description,
        "options": options or [],
    }
    if message:
        result["message"] = message
    return result


def _clean_json_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    if "{" in text and "}" in text:
        return text[text.find("{"):text.rfind("}") + 1]
    return text


def _load_api_key() -> str | None:
    if load_dotenv is not None:
        env_path = Path(__file__).resolve().parents[1] / ".env"
        load_dotenv(dotenv_path=env_path, override=True)
    return os.getenv("GEMINI_API_KEY")


def _call_gemini_json(prompt: str) -> dict:
    api_key = _load_api_key()
    if not api_key:
        raise RuntimeError("尚未設定 GEMINI_API_KEY。")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL_NAME}:generateContent"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.6,
            "responseMimeType": "application/json",
        },
    }
    response = requests.post(
        url,
        params={"key": api_key},
        json=payload,
        timeout=60,
    )
    if response.status_code >= 400:
        try:
            error = response.json().get("error", {})
            message = error.get("message") or response.text
        except ValueError:
            message = response.text
        raise RuntimeError(f"Gemini API 錯誤：{message}")

    data = response.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Gemini 回傳格式異常：{exc}")

    return json.loads(_clean_json_text(text))


def _build_prompt(state: dict) -> str:
    structured = state.get("structured_request") or {}
    selected = state.get("selected") or {}
    hotel = structured.get("hotel_preferences") or {}
    flight = selected.get("flight") or {}

    return f"""
你是一位住宿推薦助理。請根據使用者的旅遊條件，推薦 3 個真實住宿候選。

請只輸出 JSON，不要 Markdown，不要額外說明。

輸出格式：
{{
  "description": "一句給使用者看的住宿推薦說明",
  "options": [
    {{
      "id": 1,
      "title": "飯店或明確住宿區域名稱",
      "detail": "住宿資訊摘要，包含地點、交通、適合原因、預估價格與注意事項",
      "reason": "推薦理由",
      "area": "區域",
      "estimated_price_twd": 4000,
      "map_query": "可直接用 Google Maps 搜尋的字串"
    }}
  ]
}}

推薦規則：
1. 必須符合目的地，不可固定輸出日本或東京。
2. 優先符合每晚住宿預算、晚數、人數、房型、是否近車站、偏好區域與備註。
3. 若預算偏低，仍推薦相對接近的區域或飯店，並在 detail 說明可能需要提高預算。
4. title 若是飯店，必須盡量是真實可被 Google Maps 搜尋的名稱；若不確定飯店，請推薦明確住宿區域。
5. map_query 必須包含目的地城市與飯店/區域名稱。
6. 請提醒實際房價與空房仍需到訂房平台確認。

structured_request:
{json.dumps(structured, ensure_ascii=False, indent=2)}

已選航班：
{json.dumps(flight, ensure_ascii=False, indent=2)}

住宿偏好：
{json.dumps(hotel, ensure_ascii=False, indent=2)}
""".strip()


def run(state: dict) -> dict:
    try:
        payload = _call_gemini_json(_build_prompt(state or {}))
        options = payload.get("options") or []
        return _result(
            "success",
            options=options,
            description=payload.get("description")
            or "以下是根據你的住宿預算、偏好區域與旅遊條件產生的住宿推薦：",
        )
    except Exception as exc:
        return _result("error", message=str(exc))
