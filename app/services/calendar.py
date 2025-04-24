from datetime import datetime, timedelta

def get_available_slots():
    base_time = datetime.utcnow()
    days = [base_time + timedelta(days=i) for i in range(5)]
    slots = {}
    for day in days:
        date_str = day.strftime("%Y-%m-%d")
        slots[date_str] = ["10:00", "13:00", "15:30"]
    return slots
