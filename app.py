from datetime import date, timedelta
from pathlib import Path
from presentation import render_results

import streamlit as st

from importlib import reload
import location_runtime

# The runtime loader itself can be cached by an older Streamlit process.
if getattr(location_runtime, "COMPONENT_VERSION", None) != 5:
    reload(location_runtime)
location_widgets = location_runtime.load_location_widgets()
from planner import INTERESTS, ItineraryGenerationError, calculate_trip_days, generate_itinerary

st.set_page_config(page_title="AI Travel Planner", page_icon="🌍", layout="centered")
location_widgets.migrate_location_state()
styles = Path(__file__).with_name("styles.css").read_text(encoding="utf-8-sig")
st.markdown(f"<style>{styles}</style>", unsafe_allow_html=True)
st.markdown('<div class="product-identity">✈ &nbsp; AI Travel Planner</div>', unsafe_allow_html=True)
if "planned_trip" in st.session_state and st.session_state.get("trip_screen") != "inputs":
    render_results(*st.session_state["planned_trip"])
    st.stop()

st.markdown('<div class="travel-eyebrow">AI-POWERED TRAVEL PLANNER</div>', unsafe_allow_html=True)
st.title("Where will your next journey take you?")
st.write("Tell us your travel plans and preferences, and we'll create a personalized itinerary just for you.")
if "planned_trip" in st.session_state:
    if st.button("View last itinerary", key="view_trip"):
        st.session_state["trip_screen"] = "results"
        st.rerun()

# A container lets dates update the duration before the button is clicked.
with st.container(border=True, key="trip_inputs"):
    st.subheader("Trip Details")
    st.caption("Tell us about your trip. We'll bring the details together.")
    left, right = st.columns(2)
    with left:
        origin = location_widgets.location_picker("From", "origin", "Search a city, e.g. Detroit, MI")
    with right:
        destination = location_widgets.location_picker("To", "destination", "Search a city, e.g. Lisbon, Portugal")
    departure, returning, people = st.columns(3)
    with departure:
        departure_date = st.date_input("Departure date", value=date.today(), key="trip_departure", persist_state="session")
    with returning:
        return_date = st.date_input("Return date", value=date.today() + timedelta(days=2), key="trip_return", persist_state="session")
    with people:
        travelers = st.number_input("Travelers", min_value=1, max_value=20, value=1, step=1, key="trip_travelers", persist_state="session")
    try:
        trip_days = calculate_trip_days(departure_date, return_date)
        st.caption(f"Your getaway: {trip_days} days · {trip_days - 1} nights · Includes departure and return days")
    except ValueError as error:
        trip_days = None
        st.error(str(error))
    left, right = st.columns(2)
    with left:
        total_budget = st.number_input("Total Budget (USD)", min_value=0.0, value=500.0, step=50.0, format="%.2f", key="trip_budget", persist_state="session")
    with right:
        transportation_percent = st.slider("Transportation Reserve (%)", 0, 100, 30, step=5, key="trip_transportation", persist_state="session")
    st.caption("One budget for your whole group. The transportation reserve covers getting there and back; it is an allocation, not a fare estimate.")
    interests = st.multiselect("Interests", INTERESTS, placeholder="Choose what you love...", key="trip_interests", persist_state="session")
    st.caption("Choose at least one interest to make this trip your own.")
    st.write("")
    submitted = st.button("✨ Craft My Trip", type="primary", use_container_width=True, key="craft_trip")
    st.caption("AI-generated planning estimates. Verify actual fares, rates, schedules, and availability before booking.")

with st.container(key="attribution"):
    st.caption("Cities: [GeoNames](https://www.geonames.org/) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Airport information: [OurAirports](https://ourairports.com/data/) · Public domain. Airport codes are suggestions, not a required airport.")

if submitted:
    st.session_state.pop("planned_trip", None)
    errors = []
    if origin is None:
        errors.append("Please select your starting location from the city suggestions.")
    if destination is None:
        errors.append("Please select a destination from the city suggestions.")
    if trip_days is None:
        errors.append("Please choose a return date after your departure date.")
    if total_budget <= 0:
        errors.append("Please enter a total budget greater than zero.")
    if not interests:
        errors.append("Please choose at least one interest.")
    for error in errors:
        st.error(error)
    if not errors:
        trip = {
            "origin": origin.label, "destination": destination.label,
            "departure_date": departure_date, "return_date": return_date,
            "trip_days": trip_days, "travelers": int(travelers),
            "total_budget": float(total_budget), "interests": list(interests),
            "transportation_percent": transportation_percent,
        }
        with st.spinner("✨ Crafting your trip..."):
            try:
                itinerary = generate_itinerary(trip)
            except ItineraryGenerationError as error:
                st.error(str(error))
            except Exception:
                # Never expose unexpected SDK/configuration details to the page.
                st.error("We couldn't craft your trip right now. Please try again shortly.")
            else:
                st.session_state["planned_trip"] = (trip, itinerary)
                st.session_state["trip_screen"] = "results"
                st.rerun()
