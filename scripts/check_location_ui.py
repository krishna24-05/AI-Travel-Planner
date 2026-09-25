"""Optional browser smoke check; never presses Craft My Trip or calls OpenAI.

Requires the dev-only playwright package and locally installed Chrome.
Run against an already-running app: python scripts/check_location_ui.py
"""
import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8501")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1100})
        page.goto(args.url)
        expect(page.get_by_text("Trip Details", exact=True)).to_be_visible(timeout=30000)
        frames = page.locator('iframe[title="streamlit_searchbox.searchbox"]')
        expect(frames).to_have_count(2, timeout=30000)
        origin = frames.nth(0).content_frame
        destination = frames.nth(1).content_frame
        origin.get_by_role("combobox").fill("Detr")
        expect(origin.get_by_text("Detroit, Michigan, USA · DTW", exact=True)).to_be_visible(timeout=15000)
        expect(origin.get_by_text("Detroit Beach", exact=False)).to_have_count(0)
        expect(page.get_by_text("Can't find your city?", exact=False)).to_have_count(0)
        option = origin.get_by_role("option").first
        expect(option).to_have_css("color", "rgb(43, 23, 23)")
        expect(origin.locator("body")).to_have_css("background-color", "rgb(255, 255, 255)")
        expect(origin.get_by_text("From", exact=True)).to_have_css("color", "rgb(43, 23, 23)")
        option.hover()
        expect(option).to_have_css("background-color", "rgb(254, 242, 242)")
        expect(origin.get_by_role("combobox")).to_have_css("color", "rgb(43, 23, 23)")
        # Check the input's visible control rather than its transparent inner input.
        control = origin.locator('div[class$="-control"]')
        expect(control).to_have_css("background-color", "rgb(255, 255, 255)")
        page.mouse.move(0, 0)
        origin.get_by_role("combobox").press("ArrowDown")
        expect(option).to_have_css("background-color", "rgb(254, 242, 242)")
        output = Path(__file__).resolve().parents[1] / ".artifacts"
        output.mkdir(exist_ok=True)
        page.screenshot(path=str(output / "city-suggestions.png"), full_page=True)
        origin.get_by_text("Detroit, Michigan, USA · DTW", exact=True).click()
        old_frame = frames.nth(0).element_handle()
        origin.locator('svg[fill="#B91C1C"]').click()
        # Clear creates a new component instance; wait for its mount before typing.
        page.wait_for_function("element => !element.isConnected", arg=old_frame)
        expect(origin.get_by_role("combobox")).to_be_visible()
        origin.get_by_role("combobox").fill("Detroit, Michigan")
        expect(origin.get_by_text("Detroit, Michigan, USA · DTW", exact=True)).to_be_visible(timeout=15000)
        origin.get_by_text("Detroit, Michigan, USA · DTW", exact=True).click()
        destination.get_by_role("combobox").fill("Hyderabad")
        expect(destination.get_by_text("Hyderabad, Telangana, India · HYD", exact=True)).to_be_visible(timeout=15000)
        destination.get_by_text("Hyderabad, Telangana, India · HYD", exact=True).click()
        expect(origin.get_by_text("Detroit, Michigan, USA · DTW", exact=True)).to_be_visible()
        expect(destination.get_by_text("Hyderabad, Telangana, India · HYD", exact=True)).to_be_visible()
        expect(page.get_by_test_id("stException")).to_have_count(0)
        page.screenshot(path=str(output / "selected-cities.png"), full_page=True)
        print("PASS: live typing, city suggestions, structured selections, and no UI exceptions. Craft My Trip was not pressed.")
        browser.close()


if __name__ == "__main__":
    main()
