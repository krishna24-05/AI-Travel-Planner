"""City selection UI; typing searches only the bundled offline index."""
import streamlit as st
from streamlit_searchbox import st_searchbox

from location_model import LOCATION_VERSION, Location
from location_search import LocationIndexError, suggest_locations

COMPONENT_VERSION = 5


def migrate_location_state():
    if st.session_state.get("location_version") != LOCATION_VERSION:
        st.session_state.pop("planned_trip", None)
        for key in list(st.session_state):
            if key.startswith("location_"):
                del st.session_state[key]
        st.session_state["location_version"] = LOCATION_VERSION


def location_picker(label, field, placeholder):
    base = f"location_{field}"
    generation = st.session_state.get(f"{base}_generation", 0)
    widget_key = f"{base}_search_{generation}"
    selected_key = f"{base}_selected"
    error_key = f"{base}_error"

    def reset():
        st.session_state[selected_key] = None
        if widget_key in st.session_state:
            st.session_state[widget_key]["result"] = None
        st.session_state.pop(error_key, None)

    def search(query):
        # The component retains its last result during a new search by default.
        # Explicitly invalidate both copies before returning new suggestions.
        reset()
        st.session_state[widget_key]["result"] = None
        try:
            return [(location.suggestion_label, location) for location in suggest_locations(query)]
        except LocationIndexError as error:
            st.session_state[error_key] = str(error)
            return []

    current = st.session_state.get(selected_key)
    selected = st_searchbox(
        search, label=label, placeholder=placeholder, key=widget_key,
        debounce=300, default=current, default_searchterm=current.suggestion_label if current else "",
        default_options=[(current.suggestion_label, current)] if current else None,
        default_use_searchterm=False, edit_after_submit="disabled", reset_function=reset,
        help="Select a city. Airport codes are optional serving-airport information, not a required airport. Clear to change cities.",
        style_overrides={
            "wrapper": {"backgroundColor": "#FFFFFF", "color": "#2B1717", "colorScheme": "light"},
            "searchbox": {
                "control": {
                    "backgroundColor": "white", "border": "1px solid #F1DADA", "borderRadius": "8px",
                    # Emotion expands & to this control's class inside the iframe.
                    # The component exposes no body/label theme overrides. Scope
                    # these rules to its document, leaving the host UI untouched.
                    "body:has(&)": {"backgroundColor": "#FFFFFF", "color": "#2B1717", "colorScheme": "light"},
                    "body:has(&) #root > div > div:first-child": {"color": "#2B1717 !important"},
                    **{
                        f'&:has(input[aria-activedescendant$="-option-{index}"]) ~ div [id$="-option-{index}"]':
                        {"backgroundColor": "#FEF2F2"}
                        for index in range(5)
                    },
                    "&:hover": {"border": "1px solid #B91C1C"},
                    "&:focus-within": {"border": "1px solid #B91C1C", "boxShadow": "0 0 0 1px #B91C1C"},
                },
                "input": {"color": "#2B1717"}, "singleValue": {"color": "#2B1717"},
                "menuList": {"backgroundColor": "#FFF7F5"},
                "placeholder": {"color": "#6B5A5A"},
                "option": {
                    "color": "#2B1717", "backgroundColor": "#FFFFFF",
                    "&:hover": {"backgroundColor": "#FEF2F2"},
                    "&:active": {"backgroundColor": "#F1DADA"},
                    "&[aria-selected=true]": {"backgroundColor": "#FEF2F2"},
                },
            },
            "clear": {"fill": "#B91C1C", "clearable": "always"},
            "dropdown": {"stroke": "#B91C1C"},
            "help": {"stroke": "#B91C1C"},
        },
    )
    st.session_state[selected_key] = selected if isinstance(selected, Location) else None
    if st.session_state.get(error_key):
        st.caption(st.session_state[error_key])

    return st.session_state[selected_key]
