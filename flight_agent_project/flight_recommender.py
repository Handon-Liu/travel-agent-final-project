import os
import re
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# 讀取 .env 檔案裡面的環境變數
load_dotenv()

# 連到 Duffel 的 API 伺服器
DUFFEL_BASE_URL = "https://api.duffel.com"
DUFFEL_VERSION = "v2"


# Demo 用匯率：之後可以改成即時匯率 API
EXCHANGE_RATES_TO_TWD = {
    "TWD": 1.0,
    "USD": 32.0,
    "JPY": 0.22,
    "EUR": 35.0,
    "GBP": 40.0,
    "HKD": 4.1,
    "KRW": 0.024,
}
# 把 Duffel 回傳的價格換算成台幣，方便後續比較價格。注意：這裡使用的是 Demo 固定匯率，不是即時匯率。
def convert_to_twd(amount: float, currency: str) -> float:
    """
    將 Duffel 回傳的價格換算成台幣。
    注意：這裡使用的是 Demo 固定匯率，不是即時匯率。
    """
    currency = currency.upper()

    if currency not in EXCHANGE_RATES_TO_TWD:
        raise ValueError(f"目前不支援將 {currency} 換算成 TWD，請先加入匯率。")

    return amount * EXCHANGE_RATES_TO_TWD[currency]


# 向 Duffel API 出示的「身份證明文件」
def get_duffel_headers() -> dict:
    """
    建立 Duffel API 所需的 headers。
    """
    access_token = os.getenv("DUFFEL_ACCESS_TOKEN")

    if not access_token:
        raise ValueError("請先在 .env 設定 DUFFEL_ACCESS_TOKEN")

    return {
        "Authorization": f"Bearer {access_token}",
        "Duffel-Version": DUFFEL_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
    }

# 檢查 Duffel API 有沒有回傳錯誤
def raise_for_duffel_error(response: requests.Response) -> None:
    """
    處理 Duffel API 錯誤訊息。
    """
    if response.ok:
        return

    try:
        error_data = response.json()
        errors = error_data.get("errors", [])
        if errors:
            first_error = errors[0]
            message = first_error.get("message", "未知 Duffel API 錯誤")
            code = first_error.get("code", "unknown_error")
            raise RuntimeError(f"Duffel API 錯誤：{code} - {message}")
    except ValueError:
        pass

    response.raise_for_status()

# 把 Duffel 回傳的飛行時間格式轉成「分鐘」
def parse_iso_duration_to_minutes(duration: str) -> int:
    """
    將 ISO 8601 duration 轉成分鐘。
    例如：
    PT2H30M -> 150
    PT45M -> 45
    """
    if not duration:
        return 0

    hours = 0
    minutes = 0

    hour_match = re.search(r"(\d+)H", duration)
    minute_match = re.search(r"(\d+)M", duration)

    if hour_match:
        hours = int(hour_match.group(1))

    if minute_match:
        minutes = int(minute_match.group(1))

    return hours * 60 + minutes

# 向 Duffel API 發送航班搜尋請求，並拿回航班 offers。  offer 是旅遊和航空 API 裡的一種「固定資料格式」
def create_offer_request(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    cabin_class: str = "economy",
    max_connections: int | None = None,
    supplier_timeout: int = 20000,
) -> dict:
    """
    呼叫 Duffel API 建立 Offer Request，並回傳航班 offers。

    origin: 出發地 IATA code，例如 TPE
    destination: 目的地 IATA code，例如 FUK
    departure_date: 出發日期，格式 YYYY-MM-DD
    adults: 成人數
    cabin_class: economy / premium_economy / business / first
    max_connections: 最大轉機次數，0 代表只找直飛
    supplier_timeout: 等待航空公司回應的時間，單位毫秒
    """
    url = f"{DUFFEL_BASE_URL}/air/offer_requests"

    params = {
        "return_offers": "true",
        "supplier_timeout": supplier_timeout,
        "view": "offers",
    }
    # Duffel API 要求 passengers 是一個 list，每個 passenger 都要有 type，這裡我們假設都是成人。
    passengers = [{"type": "adult"} for _ in range(adults)]

    #給 Duffel 的搜尋條件
    data = {
        "slices": [
            {
                "origin": origin,
                "destination": destination,
                "departure_date": departure_date,
            }
        ],
        "passengers": passengers,
        "cabin_class": cabin_class,
    }

    if max_connections is not None:
        data["max_connections"] = max_connections

    payload = {
        "data": data
    }
    # 向 Duffel API 發送 POST 請求，並處理回應
    response = requests.post(
        url,
        headers=get_duffel_headers(),
        params=params,
        json=payload,
        timeout=90,
    )

    raise_for_duffel_error(response)

    # 回傳 Duffel 的航班資料
    return response.json()["data"]


def get_airport_code(airport_obj: dict) -> str:
    """
    從 Duffel 的 airport 物件中取出 IATA code。
    """
    if not airport_obj:
        return ""

    return airport_obj.get("iata_code", "")


def is_duffel_mock_offer(offer: dict) -> bool:
    """
    判斷 Duffel offer 是否為 test mode 的 Duffel Airways mock data。
    Duffel Airways 的 IATA code 是 ZZ。
    """
    owner = offer.get("owner", {}) or {}

    owner_name = owner.get("name", "")
    owner_iata_code = owner.get("iata_code", "")

    if owner_name == "Duffel Airways" or owner_iata_code == "ZZ":
        return True

    # 保險起見，也檢查每個航段的 marketing carrier / operating carrier
    for slice_item in offer.get("slices", []):
        for segment in slice_item.get("segments", []):
            marketing_carrier = segment.get("marketing_carrier", {}) or {}
            operating_carrier = segment.get("operating_carrier", {}) or {}

            marketing_name = marketing_carrier.get("name", "")
            marketing_iata = marketing_carrier.get("iata_code", "")

            operating_name = operating_carrier.get("name", "")
            operating_iata = operating_carrier.get("iata_code", "")

            if marketing_name == "Duffel Airways" or marketing_iata == "ZZ":
                return True

            if operating_name == "Duffel Airways" or operating_iata == "ZZ":
                return True

    return False



# 把 Duffel 回傳的複雜 JSON 航班資料，整理成 pandas DataFrame 表格
def normalize_duffel_offers(offer_request: dict,exclude_mock_airlines: bool = True,) -> pd.DataFrame:
    """
    將 Duffel offer request 裡面的 offers 整理成表格，一個 offer 可以理解成：一組可購買的航班選項。
    exclude_mock_airlines=True 時，會排除 Duffel Airways / ZZ 這類測試航班。
    """
    offers = offer_request.get("offers", [])
    rows = []
    #slices 是旅程段落，例如單程就是一個 slice(像是TPE → FUK)，來回就是兩個 slice。每個 slice 裡面有 segments，代表實際的飛行段落。
    #例如直飛：TPE → FUK，segments 數量是 1；轉機一次：TPE → ICN 、ICN → FUK，segments 數量是 2
    for offer in offers:
        if exclude_mock_airlines and is_duffel_mock_offer(offer):
            continue
        slices = offer.get("slices", [])

        if not slices:
            continue

        all_segments = []
        for slice_item in slices:
            all_segments.extend(slice_item.get("segments", []))

        if not all_segments:
            continue
        #找出出發機場/時間，和抵達機場/時間
        first_segment = all_segments[0]
        last_segment = all_segments[-1]

        #整理航空公司與航班編號，例如：長榮航空 BR123，ANA NH456
        airline_names = []
        airline_codes = []
        flight_numbers = []

        for segment in all_segments:
            carrier = segment.get("marketing_carrier", {}) or {}
            carrier_code = carrier.get("iata_code", "")
            carrier_name = carrier.get("name", "")

            if carrier_code:
                airline_codes.append(carrier_code)

            if carrier_name:
                airline_names.append(carrier_name)

            flight_number = segment.get("marketing_carrier_flight_number", "")
            if carrier_code and flight_number:
                flight_numbers.append(f"{carrier_code}{flight_number}")
        #計算總飛行時間和轉機次數
        duration_min = sum(
            parse_iso_duration_to_minutes(slice_item.get("duration", ""))
            for slice_item in slices
        )

        # 對單程來說，stops = segments(航段數量) - 1
        # 對來回票來說，這裡會把每個 slice 的轉機次數加總
        stops = sum(
            max(len(slice_item.get("segments", [])) - 1, 0)
            for slice_item in slices
        )

        origin_code = get_airport_code(first_segment.get("origin", {}))
        destination_code = get_airport_code(last_segment.get("destination", {}))

        original_price = float(offer.get("total_amount", 0))
        original_currency = offer.get("total_currency", "")

        price_twd = convert_to_twd(
            amount=original_price,
            currency=original_currency,
)

        rows.append({
            "source": "Duffel",
            "offer_id": offer.get("id", ""),
            "expires_at": offer.get("expires_at", ""),                              #這個報價（Offer）的截止有效時間
            "airline": "/".join(sorted(set(airline_codes))),
            "airline_name": "/".join(sorted(set(airline_names))),
            "flight_numbers": " → ".join(flight_numbers),
            "origin": origin_code,
            "destination": destination_code,
            "departure_time": first_segment.get("departing_at", ""),
            "arrival_time": last_segment.get("arriving_at", ""),
            "duration_min": duration_min,
            "stops": stops,
            "price": float(offer.get("total_amount", 0)),
            # 原始 API 價格
            "original_price": original_price,
            "original_currency": original_currency,

            # 台幣換算價格
            "price_twd": round(price_twd, 0),
            "display_currency": "TWD",
        })

    return pd.DataFrame(rows)


def normalize_score(series: pd.Series, lower_is_better: bool = True) -> pd.Series:
    """
    將數值轉換成 0~1 分數。
    lower_is_better=True 代表數值越小越好，例如價格、時間、轉機次數。
    """
    if series.empty:
        return series

    min_value = series.min()
    max_value = series.max()

    if min_value == max_value:
        return pd.Series([1.0] * len(series), index=series.index)

    normalized = (series - min_value) / (max_value - min_value)

    if lower_is_better:
        return 1 - normalized

    return normalized

# 判斷航班出發時間是否符合使用者偏好的時段，例如早上、下午、晚上、夜間
def get_time_preference_score(departure_time: str, preference: str = "any") -> float:
    """
    根據使用者偏好的出發時段給分。
    """
    if preference == "any":
        return 1.0

    if not departure_time:
        return 0.5

    try:
        hour = datetime.fromisoformat(departure_time).hour
    except ValueError:
        return 0.5

    time_ranges = {
        "morning": range(6, 12),
        "afternoon": range(12, 18),
        "evening": range(18, 22),
        "night": list(range(22, 24)) + list(range(0, 6)),
    }

    return 1.0 if hour in time_ranges.get(preference, []) else 0.3

# 根據價格、時間、轉機次數、出發時段偏好推薦航班，並且產生推薦理由
def make_recommendation_reason(row: pd.Series) -> str:
    """
    產生推薦理由。
    """
    reasons = []

    if row["stops"] == 0:
        reasons.append("直飛，轉機風險較低")
    else:
        reasons.append(f"需轉機 {int(row['stops'])} 次")

    reasons.append(f"總飛行時間約 {int(row['duration_min'])} 分鐘")

    passenger_count = int(row.get("passenger_count", 1) or 1)
    price_twd = float(row.get("price_twd", 0) or 0)
    price_per_person_twd = float(
        row.get("price_per_person_twd", price_twd / passenger_count) or 0
    )
    reasons.append(
        f"單程總價 TWD {price_twd:,.0f}，單程每人 TWD {price_per_person_twd:,.0f}"
        f"（原始價格：{row['original_currency']} {row['original_price']:.2f}）"
    )

    if row.get("airline_name"):
        reasons.append(f"航空公司為 {row['airline_name']}")

    return "；".join(reasons)

def recommend_flights(
    df: pd.DataFrame,
    top_n: int = 5,
    time_preference: str = "any",
    max_budget: float | None = None,
    max_budget_per_person: float | None = None,
) -> pd.DataFrame:
    """
    根據價格、時間、轉機次數、出發時段偏好推薦航班。
    max_budget 為單程整筆訂單總預算；max_budget_per_person 為每人單程航班預算。
    """
    if df.empty:
        return df

    result = df.copy()

    if max_budget_per_person is not None and "price_per_person_twd" in result.columns:
        result = result[result["price_per_person_twd"] <= max_budget_per_person].copy()
    elif max_budget is not None:
        result = result[result["price_twd"] <= max_budget].copy()       # keep flights within total budget

    if result.empty:
        return result

    result["price_score"] = normalize_score(result["price_twd"], lower_is_better=True)
    result["duration_score"] = normalize_score(result["duration_min"], lower_is_better=True)
    result["stops_score"] = normalize_score(result["stops"], lower_is_better=True)
    result["time_preference_score"] = result["departure_time"].apply(
        lambda x: get_time_preference_score(x, time_preference)     # 依使用者偏好的出發時段加分
    )

    result["score"] = (
        0.45 * result["price_score"]
        + 0.25 * result["duration_score"]
        + 0.20 * result["stops_score"]
        + 0.10 * result["time_preference_score"]
    )

    result = result.sort_values(by="score", ascending=False)
    result["recommendation_reason"] = result.apply(make_recommendation_reason, axis=1) # 產生可讀的推薦原因

    return result.head(top_n)

def save_to_excel(
    all_flights_df: pd.DataFrame,
    recommended_df: pd.DataFrame,
    output_path: str,
) -> None:
    """
    將所有航班與推薦航班存成 Excel。
    """
    # output/ 資料夾還不存在，它會自動建立
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True) # 確保輸出資料夾存在
    
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        all_flights_df.to_excel(writer, sheet_name="all_flights", index=False)
        recommended_df.to_excel(writer, sheet_name="recommended_flights", index=False)

# 整合整個 Duffel 航班推薦流程，從建立 offer request、取得 offers、整理成 DataFrame、計算推薦分數、輸出 Excel，到回傳推薦航班
def run_duffel_flight_recommendation_pipeline(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    cabin_class: str = "economy",
    non_stop: bool = False,
    time_preference: str = "any",
    max_budget: float | None = None,
    max_budget_per_person: float | None = None,
    max_connections: int | None = None,
    top_n: int = 5,
    output_path: str = "output/duffel_flight_recommendations.xlsx",
    exclude_mock_airlines: bool = True,
) -> pd.DataFrame:
    """
    Duffel 航班推薦完整流程：
    1. 建立 Duffel Offer Request
    2. 取得 offers
    3. 整理成 DataFrame
    4. 計算推薦分數
    5. 輸出 Excel
    6. 回傳推薦航班
    """
    if max_connections is None:
        max_connections = 0 if non_stop else None

    offer_request = create_offer_request(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        adults=adults,
        cabin_class=cabin_class,
        max_connections=max_connections,
    )

    all_flights_df = normalize_duffel_offers(offer_request,exclude_mock_airlines=True,)

    if not all_flights_df.empty:
        passenger_count = max(int(adults or 1), 1)
        all_flights_df["passenger_count"] = passenger_count
        all_flights_df["price_per_person_twd"] = (
            all_flights_df["price_twd"] / passenger_count
        ).round(0)
        all_flights_df["original_price_per_person"] = (
            all_flights_df["original_price"] / passenger_count
        ).round(2)

    if all_flights_df.empty:
        print("本次搜尋結果在排除 Duffel Airways mock data 後沒有可用航班。")
        print("這通常是因為目前使用 Duffel test mode，真實航空公司 sandbox availability 不穩定。")
        return all_flights_df

    recommended_df = recommend_flights(
        all_flights_df,
        top_n=top_n,
        time_preference=time_preference,
        max_budget=max_budget,
        max_budget_per_person=max_budget_per_person,
    )

    save_to_excel(
        all_flights_df=all_flights_df,
        recommended_df=recommended_df,
        output_path=output_path,
    )

    return recommended_df


if __name__ == "__main__":
    recommended = run_duffel_flight_recommendation_pipeline(
        origin="TPE",
        destination="FUK",
        departure_date="2026-07-01",
        adults=1,
        cabin_class="economy",
        non_stop=False,
        time_preference="morning",
        max_budget=None,
        top_n=5,
        output_path="output/TPE_to_FUK_duffel_flights.xlsx",
    )

    print(recommended[
        [
            "airline_name",
            "flight_numbers",
            "departure_time",
            "arrival_time",
            "duration_min",
            "stops",
            "price_twd",
            "display_currency",
            "original_price",
            "original_currency",
            "score",
            "recommendation_reason",
        ]
    ])
