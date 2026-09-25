"""Dev-only browser check of seeded results and mobile layout. No API calls."""
from pathlib import Path
import os
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory() as temporary:
        fixture = Path(temporary) / 'preview.py'
        fixture.write_text(f'''
import sys, runpy
sys.path.insert(0, {str(ROOT)!r})
sys.path.insert(0, {str(ROOT / 'tests')!r})
from unittest.mock import patch
from datetime import date
import streamlit as st
from test_presentation import itinerary
from location_widgets import migrate_location_state
from location_search import suggest_locations
migrate_location_state()
if 'preview_seeded' not in st.session_state:
    st.session_state['preview_seeded'] = True
    st.session_state['location_origin_selected'] = suggest_locations('Detr')[0]
    st.session_state['location_destination_selected'] = suggest_locations('Par')[0]
    trip = dict(origin='Detroit, Michigan, USA', destination='Paris, France',
                departure_date=date(2026, 9, 1), return_date=date(2026, 9, 3),
                trip_days=3, travelers=2, total_budget=1100, transportation_percent=30,
                interests=['Museums', 'Nature', 'Art'])
    sample = itinerary().replace('Budget-friendly option to investigate: bus.',
        '- **Budget-friendly option to investigate:** Ferry — Consider transfers.\\n'
        '- **Alternative to investigate:** Coach — Check baggage rules.')
    st.session_state['planned_trip'] = (trip, sample)
with patch('planner.OpenAI', side_effect=AssertionError('OpenAI forbidden in preview')):
    runpy.run_path({str(ROOT / 'app.py')!r}, run_name='__main__')
''', encoding='utf-8')
        with tempfile.TemporaryFile() as log:
            server = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(fixture),
                                       '--server.headless=true', '--server.address=127.0.0.1',
                                       f'--server.port={port}', '--browser.gatherUsageStats=false'],
                                      cwd=ROOT, stdout=log, stderr=log,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                url = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        with urlopen(url + '/_stcore/health', timeout=1):
                            break
                    except OSError:
                        time.sleep(.2)
                with sync_playwright() as p:
                    browser = p.chromium.launch(channel='chrome', headless=True)
                    page = browser.new_page(viewport={'width': 1280, 'height': 1000})
                    page.goto(url)
                    expect(page.get_by_role('heading', name='Paris Adventure')).to_be_visible(timeout=30000)
                    expect(page.get_by_test_id('stException')).to_have_count(0)
                    heading = page.get_by_role('heading', name='Paris Adventure')
                    assert 50 <= heading.bounding_box()['y'] < 160, 'Results top spacing'
                    expect(page.get_by_test_id('stHeader')).to_have_css('background-color', 'rgb(255, 250, 248)')
                    expect(page.locator('.allocation-row')).to_have_count(5)
                    expect(page.get_by_text('Ferry — Consider transfers.', exact=True)).to_be_visible()
                    page.get_by_role('tab', name='Day 3', exact=True).click()
                    expect(page.get_by_role('tab', name='Day 3', exact=True)).to_have_css('background-color', 'rgb(254, 242, 242)')
                    expect(page.get_by_text('Morning: Explore 3.', exact=False)).to_be_visible()
                    output = ROOT / '.artifacts'
                    output.mkdir(exist_ok=True)
                    expect(page.get_by_text('A little structure, with room to explore.', exact=True).locator('..')).to_have_css('opacity', '1')
                    expect(page.locator('.st-key-result_overview')).to_have_css('background-color', 'rgb(255, 255, 255)')
                    page.get_by_role('heading', name='Paris Adventure').scroll_into_view_if_needed()
                    page.screenshot(path=str(output / 'results-desktop.png'), full_page=True)
                    for width in (390, 320):
                        page.set_viewport_size({'width': width, 'height': 844})
                        page.get_by_test_id('stMain').evaluate('e => e.scrollTop = 0')
                        assert 50 <= heading.bounding_box()['y'] < 170, 'Mobile results top spacing'
                        page.screenshot(path=str(output / f'results-{width}.png'), full_page=True)
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Results overflow'
                    page.get_by_role('button', name='← Edit Trip', exact=True).click()
                    expect(page.get_by_role('heading', name='Trip Details')).to_be_visible()
                    frames = page.locator('iframe[title="streamlit_searchbox.searchbox"]')
                    expect(frames.nth(0).content_frame.get_by_role('combobox')).to_have_value('Detroit, Michigan, USA · DTW')
                    expect(frames.nth(1).content_frame.get_by_role('combobox')).to_have_value('Paris, France · CDG / ORY')
                    for width in (1280, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 844})
                        page.get_by_test_id('stMain').evaluate('e => e.scrollTop = 0')
                        hero = page.get_by_role('heading', name='Where will your next journey take you?')
                        hero_box = hero.bounding_box()
                        header_box = page.get_by_test_id('stHeader').bounding_box()
                        assert hero_box['y'] >= header_box['y'] + header_box['height'], 'Hero overlaps header'
                        assert hero_box['y'] + hero_box['height'] < 844, 'Hero clipped'
                        page.screenshot(path=str(output / f'planner-{width}.png'), full_page=True)
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Form overflow'
                    expect(page.get_by_test_id('stException')).to_have_count(0)
                    page.get_by_role('button', name='View last itinerary', exact=True).click()
                    expect(page.get_by_role('heading', name='Paris Adventure')).to_be_visible()
                    browser.close()
                    print('PASS: results, day selection, Edit Trip, retained cities, and 390/320px layouts. Zero OpenAI calls.')
            finally:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(server.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    server.terminate()
                server.wait(timeout=10)


if __name__ == '__main__':
    main()
