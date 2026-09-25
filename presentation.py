"""Lossless presentation of the planner's existing Markdown contract."""
import re
from html import escape

import streamlit as st

from budget import calculate_budget

SECTION_NAMES = ("Trip Overview", "Transportation", "Budget", "Day-by-Day Itinerary", "Practical Notes")


def split_sections(markdown):
    """Only split the exact contract; unfamiliar output stays intact."""
    lines = markdown.splitlines(keepends=True)
    headings = [(i, line.strip()[2:]) for i, line in enumerate(lines) if line.startswith("# ")]
    if tuple(name for _, name in headings) != SECTION_NAMES:
        return None
    if any(line.strip() for line in lines[:headings[0][0]]):
        return None
    return {name: "".join(lines[start + 1:end]) for (start, name), end in
            zip(headings, [i for i, _ in headings[1:]] + [len(lines)])}


def split_days(markdown, expected_days):
    lines = markdown.splitlines(keepends=True)
    headings = []
    for i, line in enumerate(lines):
        match = re.fullmatch(r"#{2,3} Day (\d+)(?:\s*[—–:-]\s*[^\n]+)?\s*", line)
        if match:
            headings.append((i, int(match[1]), line.lstrip("# ").strip()))
    if [number for _, number, _ in headings] != list(range(1, expected_days + 1)):
        return None
    if any(line.strip() for line in lines[:headings[0][0]]):
        return None
    return [(title, "".join(lines[start + 1:end])) for (start, _, title), end in
            zip(headings, [i for i, _, _ in headings[1:]] + [len(lines)])]


def split_transport_options(markdown):
    """Recognize only two explicitly labeled option blocks; otherwise keep Markdown."""
    pattern = re.compile(
        r"^(?:[-*] |\d+[.)] |#{2,3} )?(?:\*\*)?"
        r"(Budget-friendly option to investigate|Alternative to investigate)"
        r"(?::\*\*|\*\*:|:)\s*(.+)$", re.IGNORECASE)
    options = []
    for line in markdown.splitlines():
        match = pattern.fullmatch(line.strip())
        if match:
            options.append([match[1], match[2]])
        elif options:
            options[-1][1] += "\n" + line
        elif line.strip():
            return None
    if len(options) != 2 or len({label.casefold() for label, _ in options}) != 2:
        return None
    return options


def budget_allocations(budget):
    """Use the existing calculator's disjoint categories, never its subtotal."""
    return [("Round-trip transportation", budget["transportation"]), *budget["categories"].items()]


def render_budget(trip, generated=None):
    budget = calculate_budget(trip["total_budget"], trip["trip_days"], trip["travelers"], trip["transportation_percent"])
    with st.container(border=True, key="budget_breakdown"):
        st.subheader("Budget Breakdown")
        st.caption("Whole-trip group budget · USD · Planning allocations, not live prices")
        st.caption("Calculated baseline allocation")
        rows = []
        for label, amount in budget_allocations(budget):
            percent = min(100.0, max(0.0, amount / trip["total_budget"] * 100))
            rows.append(f'<div class="allocation-row"><div><span>{escape(label)}</span>'
                        f'<strong>USD {amount:,.2f}</strong></div><div class="allocation-track" aria-hidden="true">'
                        f'<div style="width:{percent:.4f}%"></div></div></div>')
        st.markdown('<div class="allocation-bars">' + ''.join(rows) + '</div>', unsafe_allow_html=True)
        st.markdown(f"**Total · USD {trip['total_budget']:,.2f}**")
        st.caption(f"Destination budget: USD {budget['destination_budget']:,.2f}, after the transportation reserve. The bars show the calculator's baseline split.")
        if generated:
            st.caption("Itinerary allocation estimates below may redistribute the destination budget, including an emergency buffer. They describe the same funds, not additional spending.")
            st.markdown(generated)


def render_results(trip, itinerary):
    st.markdown('<div class="travel-eyebrow">YOUR PERSONALIZED GETAWAY</div>', unsafe_allow_html=True)
    st.title(trip["destination"].split(",")[0] + " Adventure")
    st.caption(f"{trip['departure_date']:%b %d, %Y} — {trip['return_date']:%b %d, %Y}")
    st.text(f"{trip['origin']} → {trip['destination']}")
    if st.button("← Edit Trip", key="edit_trip"):
        st.session_state["trip_screen"] = "inputs"
        st.rerun()
    interests = trip["interests"]
    metrics = ((f"{trip['trip_days']} days", "Trip duration"), (str(trip["travelers"]), "Travelers"),
               (f"${trip['total_budget']:,.2f}", "Total budget · USD"),
               (", ".join(interests[:2]) + (f" +{len(interests)-2}" if len(interests)>2 else ""), "Interests"))
    st.markdown('<div class="summary-grid">' + ''.join(
        f'<div class="summary-card"><strong>{escape(value)}</strong><span>{label}</span></div>'
        for value, label in metrics) + '</div>', unsafe_allow_html=True)
    if len(interests) > 2:
        st.caption("Your interests: " + " · ".join(interests))
    st.caption("AI-generated planning estimates. Verify actual fares, rates, schedules, and availability before booking.")
    sections = split_sections(itinerary)
    if sections is None:
        render_budget(trip)
        with st.container(border=True, key="result_fallback"):
            st.subheader("Your Itinerary")
            st.markdown(itinerary)
        return
    with st.container(border=True, key="result_overview"):
        st.subheader("Trip Overview")
        st.markdown(sections["Trip Overview"])
    render_budget(trip, sections["Budget"])
    with st.container(border=True, key="result_transportation"):
        st.subheader("Transportation")
        options = split_transport_options(sections["Transportation"])
        if options is None:
            st.markdown(sections["Transportation"])
        else:
            for column, (label, content) in zip(st.columns(2), options):
                with column:
                    with st.container(border=True):
                        st.caption(label)
                        st.markdown(content)
        st.caption("No live transportation data. Verify fares, schedules, baggage rules, travel times and availability with the provider.")
    with st.container(border=True, key="result_days"):
        st.subheader("Day-by-Day Itinerary")
        st.caption("A little structure, with room to explore.")
        days = split_days(sections["Day-by-Day Itinerary"], trip["trip_days"])
        if days is None:
            st.markdown(sections["Day-by-Day Itinerary"])
        elif len(days) <= 7:
            for tab, (title, body) in zip(st.tabs([f"Day {i+1}" for i in range(len(days))]), days):
                with tab:
                    st.markdown(f"#### {title}")
                    st.markdown(body)
        else:
            for i, (title, body) in enumerate(days):
                with st.expander(title, expanded=i == 0):
                    st.markdown(body)
    with st.container(border=True, key="result_notes"):
        st.subheader("Practical Notes")
        st.markdown(sections["Practical Notes"])
