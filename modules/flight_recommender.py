from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from flight_agent_project.flight_recommender import (
        run_duffel_flight_recommendation_pipeline,
    )
except ImportError:
    run_duffel_flight_recommendation_pipeline = None


MODULE_NAME = "flight_recommender"


def _result(status: str, options=None, message: str = "") -> dict:
    result = {
        "module": MODULE_NAME,
        "status": status,
        "options": options or [],
    }
    if message:
        result["message"] = message
    return result


def _get_time_preference(flight_preferences: dict) -> str:
    preferred_time = (flight_preferences or {}).get("preferred_departure_time")
    if not preferred_time:
        return "any"

    text = str(preferred_time).lower()
    if any(word in text for word in ["morning", "上午", "早上"]):
        return "morning"
    if any(word in text for word in ["afternoon", "下午"]):
        return "afternoon"
    if any(word in text for word in ["evening", "night", "晚上", "夜間"]):
        return "evening"
    return "any"




def _get_max_connections(flight_preferences: dict):
    max_transfer_count = (flight_preferences or {}).get("max_transfer_count")
    if max_transfer_count is not None and max_transfer_count != "":
        try:
            return int(max_transfer_count)
        except (TypeError, ValueError):
            pass

    transfer_text = str((flight_preferences or {}).get("transfer_preference") or "")
    if "直飛" in transfer_text:
        return 0
    if "一次" in transfer_text or "1" in transfer_text:
        return 1
    if "兩次" in transfer_text or "二次" in transfer_text or "2" in transfer_text:
        return 2

    if bool((flight_preferences or {}).get("prefer_direct")):
        return 0
    return None

def _format_datetime(value) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.replace("T", " ")[:16]


def _format_twd(value) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value or "")


def _build_no_flight_message(origin, destination, departure_date, budget_per_person, max_connections):
    route_text = f"{origin} 到 {destination}"
    parts = [f"沒有查到符合條件的航班（{route_text}，{departure_date}）。"]

    if budget_per_person:
        parts.append(
            f"目前設定的每人單程機票預算約 TWD {_format_twd(budget_per_person)}，可能低於這段航線或日期的實際票價。"
        )

    if max_connections == 0:
        parts.append("另外目前限制為直飛，直飛航班可能較少或價格較高。")
    elif max_connections is not None:
        parts.append(f"目前最多接受轉機 {max_connections} 次，這也可能讓可選航班變少。")

    parts.append("建議提高每人單程機票預算、放寬轉機限制，或改查其他出發日期。")
    return "".join(parts)


def _dataframe_to_options(df) -> list[dict]:
    options = []
    for idx, (_, row) in enumerate(df.head(5).iterrows(), start=1):
        airline = row.get("airline_name", "")
        flight_numbers = row.get("flight_numbers", "")
        price_twd = _format_twd(row.get("price_twd", ""))
        price_per_person_twd = _format_twd(row.get("price_per_person_twd", ""))
        stops = row.get("stops", "")
        duration_min = row.get("duration_min", "")
        reason = row.get("recommendation_reason", "")

        title = f"{airline} {flight_numbers}".strip() or f"推薦航班 {idx}"
        detail = (
            f"出發：{_format_datetime(row.get('departure_time'))}；"
            f"抵達：{_format_datetime(row.get('arrival_time'))}；"
            f"轉機：{stops} 次；"
            f"飛行時間：約 {duration_min} 分鐘；"
            f"票價：單程總價 TWD {price_twd}，單程每人 TWD {price_per_person_twd}；"
            f"推薦原因：{reason}"
        )
        bullets = [
            f"出發：{_format_datetime(row.get('departure_time'))}",
            f"抵達：{_format_datetime(row.get('arrival_time'))}",
            f"轉機：{stops} 次",
            f"飛行時間：約 {duration_min} 分鐘",
        ]
        if reason:
            bullets.append(f"推薦原因：{reason}")
        options.append({
            "id": idx,
            "title": title,
            "detail": detail,
            "bullets": bullets,
            "price_twd": price_twd,
            "price_per_person_twd": price_per_person_twd,
        })
    return options


def run(structured_request: dict) -> dict:
    if load_dotenv is None:
        return _result("error", message="尚未安裝 python-dotenv。")

    if run_duffel_flight_recommendation_pipeline is None:
        return _result("error", message="無法載入 flight_agent_project.flight_recommender。")

    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=project_root / "flight_agent_project" / ".env", override=True)

    origin = structured_request.get("departure_airport")
    destination = structured_request.get("arrival_airport")
    departure_date = structured_request.get("start_date")
    adults = structured_request.get("people") or 1
    flight_preferences = structured_request.get("flight_preferences") or {}
    max_budget_per_person = (
        flight_preferences.get("flight_budget_twd_per_person")
        or structured_request.get("flight_budget_twd_per_person")
        or structured_request.get("budget_twd")
    )
    max_connections = _get_max_connections(flight_preferences)
    non_stop = max_connections == 0
    time_preference = _get_time_preference(flight_preferences)

    missing_fields = [
        field
        for field, value in {
            "departure_airport": origin,
            "arrival_airport": destination,
            "start_date": departure_date,
        }.items()
        if not value
    ]
    if missing_fields:
        return _result(
            "need_more_info",
            message="缺少航班查詢必要欄位：" + "、".join(missing_fields),
        )

    try:
        output_dir = project_root / "flight_agent_project" / "output"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"{origin}_to_{destination}_{departure_date}_duffel_flights.xlsx"

        df = run_duffel_flight_recommendation_pipeline(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            adults=int(adults),
            cabin_class="economy",
            non_stop=non_stop,
            time_preference=time_preference,
            max_budget_per_person=float(max_budget_per_person) if max_budget_per_person else None,
            max_connections=max_connections,
            top_n=5,
            output_path=str(output_path),
        )
        options = _dataframe_to_options(df)
        if not options:
            return _result(
                "error",
                message=_build_no_flight_message(
                    origin,
                    destination,
                    departure_date,
                    max_budget_per_person,
                    max_connections,
                ),
            )

        return _result("success", options=options)
    except Exception as e:
        return _result("error", message=str(e))
