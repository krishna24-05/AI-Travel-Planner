"""Budget allocations, not market prices."""
from math import isfinite


def transportation_allocation(total_budget, percentage):
    """Placeholder reserve; replace this step with a future data source."""
    return round(total_budget * percentage / 100, 2)


def calculate_budget(total_budget, trip_days, travelers, transportation_percent=30):
    if not isfinite(total_budget) or total_budget <= 0:
        raise ValueError("Please enter a total budget greater than zero.")
    if trip_days < 1 or travelers < 1:
        raise ValueError("Days and travelers must be positive.")
    if not 0 <= transportation_percent <= 100:
        raise ValueError("Transportation percentage must be between 0 and 100.")
    transportation = transportation_allocation(total_budget, transportation_percent)
    remaining = round(round(total_budget, 2) - transportation, 2)
    categories = {
        "Accommodation": round(remaining * .40, 2),
        "Food": round(remaining * .25, 2),
        "Local transportation": round(remaining * .15, 2),
    }
    # The remainder keeps rounded category amounts equal to the available budget.
    categories["Activities"] = round(remaining - sum(categories.values()), 2)
    return {
        "transportation": transportation,
        "destination_budget": remaining,
        "categories": categories,
        "daily_destination_budget": remaining / trip_days,
        "daily_per_traveler": remaining / trip_days / travelers,
    }
