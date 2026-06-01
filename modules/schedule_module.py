# -*- coding: utf-8 -*-
"""Generate a structured travel schedule from upstream itinerary modules."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

try:
    from google import genai
    from google.genai import types
    from pydantic import BaseModel, Field
except ImportError as exc:
    raise RuntimeError(
        "Missing dependencies. Run: pip install google-genai pydantic"
    ) from exc


class DailyScheduleItem(BaseModel):
    day: str = Field(description="Day label and date when available")
    hotel: str = Field(description="Hotel used as the daily start or end point")
    morning: str = Field(description="Morning itinerary including locations")
    afternoon: str = Field(description="Afternoon itinerary including locations")
    evening: str = Field(description="Evening itinerary including restaurant when available")
    transportation: str = Field(description="Recommended routes and transport modes")
    airport_transfer: str = Field(
        description="Airport transfer on arrival or departure days, otherwise an empty string"
    )
    notes: str = Field(description="Items requiring confirmation, such as opening hours")


class ScheduleResponse(BaseModel):
    schedule: list[DailyScheduleItem] = Field(
        description="Daily schedule combining airports, hotels, attractions, and restaurants"
    )


REQUIRED_LIST_FIELDS = ("flights", "hotels", "attractions", "restaurants")


def load_json(path: str | Path) -> dict[str, Any]:
    """Load an itinerary JSON object from disk."""
    with Path(path).open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("The itinerary JSON root must be an object.")
    return data


def validate_input(itinerary: dict[str, Any]) -> None:
    """Reject incomplete upstream data before making an API request."""
    if not isinstance(itinerary, dict):
        raise ValueError("itinerary must be a dictionary.")

    plan = itinerary.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("plan must be a dictionary.")

    days = plan.get("days")
    if not isinstance(days, int) or days < 1:
        raise ValueError("plan.days must be a positive integer.")

    for field in REQUIRED_LIST_FIELDS:
        value = itinerary.get(field)
        if not isinstance(value, list):
            raise ValueError(f"{field} must be a list.")

    if not itinerary["flights"]:
        raise ValueError("At least one flight is required to arrange airport transfers.")
    if not itinerary["hotels"]:
        raise ValueError("At least one hotel is required to arrange the daily schedule.")


def build_prompt(itinerary: dict[str, Any]) -> str:
    """Create the constrained scheduling prompt sent to Gemini."""
    return f"""
You are the schedule module of a travel-planning system.
Generate a practical daily itinerary in Traditional Chinese using only the input JSON.

Scheduling rules:
1. Return exactly the number of days specified by plan.days.
2. Arrival day: airport -> hotel luggage drop-off or check-in -> nearby attraction or rest -> restaurant when suitable.
3. Departure day: hotel -> nearby activity when time permits -> airport. Reserve sufficient airport transfer time.
4. Other days must start or end at the hotel.
5. Group attractions and restaurants by area to reduce unnecessary travel.
6. Consider flight times, meal periods, and any opening-hours information provided in the input.
7. Do not invent additional hotels, attractions, or restaurants.
8. Do not claim real-time prices, availability, or opening status. Put items requiring manual confirmation in notes.
9. Fill airport_transfer on arrival and departure days. Use an empty string on other days.
10. Return JSON matching the supplied schema without extra commentary.

Input JSON:
{json.dumps(itinerary, ensure_ascii=False, indent=2)}
""".strip()


def validate_schedule(schedule: list[dict[str, Any]], expected_days: int) -> None:
    """Apply deterministic checks after Gemini returns a schedule."""
    if len(schedule) != expected_days:
        raise ValueError(
            f"Gemini returned {len(schedule)} schedule days; expected {expected_days}."
        )

    if not schedule[0].get("airport_transfer", "").strip():
        raise ValueError("Arrival day must include airport_transfer.")
    if not schedule[-1].get("airport_transfer", "").strip():
        raise ValueError("Departure day must include airport_transfer.")


def generate_schedule(
    itinerary: dict[str, Any],
    api_key: str | None = None,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    """Generate and validate a schedule that can be inserted into itinerary['schedule']."""
    validate_input(itinerary)

    if client is None:
        api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY before generating a schedule.")
        client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=build_prompt(itinerary),
        config=types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json",
            response_schema=ScheduleResponse,
        ),
    )
    result = json.loads(response.text)
    schedule = result.get("schedule", [])
    validate_schedule(schedule, itinerary["plan"]["days"])
    return schedule


def generate_itinerary(
    itinerary: dict[str, Any],
    api_key: str | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Return a copy of the upstream itinerary with schedule filled in."""
    result = dict(itinerary)
    result["schedule"] = generate_schedule(result, api_key=api_key, client=client)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a travel schedule with Gemini.")
    parser.add_argument("input", help="Path to the upstream itinerary JSON file.")
    parser.add_argument("-o", "--output", default="generated_itinerary.json")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate upstream JSON without calling Gemini.",
    )
    args = parser.parse_args()

    itinerary = load_json(args.input)
    validate_input(itinerary)
    if args.validate_only:
        print("Input JSON is valid.")
        return

    result = generate_itinerary(itinerary)
    with Path(args.output).open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    print(f"Generated itinerary: {args.output}")


if __name__ == "__main__":
    main()
