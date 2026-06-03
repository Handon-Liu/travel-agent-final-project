def export_trip_to_txt(plan_text, filename="trip_plan.txt"):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(plan_text)

    return filename