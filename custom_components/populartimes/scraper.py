"""CDP scraper for Google Maps popular times data using pychrome."""

import logging
import re
import time
import urllib.parse
from datetime import datetime

import pychrome

from .const import DAYS_EN

_LOGGER = logging.getLogger(__name__)

# Regex patterns for German and English aria-labels
RE_LIVE_DE = re.compile(
    r"Derzeit zu (\d+)\s*% ausgelastet;?\s*normal sind (\d+)\s*%"
)
RE_LIVE_EN = re.compile(
    r"Currently (\d+)\s*% busy.*?usually (\d+)\s*%"
)
RE_HOURLY_DE = re.compile(
    r"Um (\d+) Uhr zu (\d+)\s*% ausgelastet"
)
RE_HOURLY_EN = re.compile(
    r"(\d+)% busy at (\d+)\s*(am|pm)"
)


class ScraperError(Exception):
    """Base exception for scraper errors."""


class ConnectionFailed(ScraperError):
    """Could not connect to CDP browser."""


def _parse_labels(labels: list[str]) -> dict:
    """Parse aria-label strings into structured popular times data."""
    times: list[list[int]] = [[0] * 24 for _ in range(7)]
    current_day = 0
    live_pct = None
    usual_pct = None

    # Track which hours we've seen in the current day to detect day boundaries
    seen_hours: set[int] = set()

    for label in labels:
        # Live data (German)
        m = RE_LIVE_DE.search(label)
        if m:
            live_pct = int(m.group(1))
            usual_pct = int(m.group(2))
            continue

        # Live data (English)
        m = RE_LIVE_EN.search(label)
        if m:
            live_pct = int(m.group(1))
            usual_pct = int(m.group(2))
            continue

        # Hourly data (German)
        m = RE_HOURLY_DE.search(label)
        if m:
            hour = int(m.group(1))
            pct = int(m.group(2))

            if hour in seen_hours:
                current_day += 1
                seen_hours = set()

            seen_hours.add(hour)
            if current_day < 7:
                times[current_day][hour] = pct
            continue

        # Hourly data (English)
        m = RE_HOURLY_EN.search(label)
        if m:
            pct = int(m.group(1))
            raw_hour = int(m.group(2))
            ampm = m.group(3)
            hour = raw_hour % 12 if ampm == "am" else (raw_hour % 12) + 12

            if hour in seen_hours:
                current_day += 1
                seen_hours = set()

            seen_hours.add(hour)
            if current_day < 7:
                times[current_day][hour] = pct
            continue

    # Map day indices to weekday names starting from today
    today_idx = datetime.now().weekday()  # 0=Monday
    popular_times = {}
    for i in range(7):
        day_name = DAYS_EN[(today_idx + i) % 7]
        popular_times[day_name] = times[i]

    return {
        "live": {
            "current_pct": live_pct,
            "usual_pct": usual_pct,
            "is_live": live_pct is not None,
        },
        "popular_times": popular_times,
    }


def _evaluate(tab, expression: str):
    """Evaluate JS expression on tab and return the result value."""
    result = tab.Runtime.evaluate(expression=expression, returnByValue=True)
    return result.get("result", {}).get("value")


def scrape_popular_times(cdp_url: str, address: str) -> dict:
    """Scrape Google Maps for popular times data via pychrome CDP.

    This is a synchronous function — call via asyncio.to_thread() or executor.

    Returns dict with keys: name, address, maps_url, live, popular_times.
    Raises ConnectionFailed or ScraperError on failure.
    """
    try:
        browser = pychrome.Browser(url=cdp_url)
    except Exception as err:
        raise ConnectionFailed(
            f"Failed to connect to CDP at {cdp_url}: {err}"
        ) from err

    tab = None
    try:
        tab = browser.new_tab()
        tab.start()

        # Enable required domains
        tab.Page.enable()
        tab.Runtime.enable()

        # Set viewport
        tab.Emulation.setDeviceMetricsOverride(
            width=1920, height=1080, deviceScaleFactor=1, mobile=False
        )

        # Navigate to Google Maps search
        search_url = (
            "https://www.google.com/maps/search/"
            + urllib.parse.quote_plus(address)
        )
        _LOGGER.debug("Navigating to %s", search_url)
        tab.Page.navigate(url=search_url)
        time.sleep(5)

        # Handle cookie consent (German or English)
        _evaluate(tab, """
            (() => {
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    const t = (btn.textContent || '').trim();
                    if (t === 'Alle akzeptieren' || t === 'Accept all') {
                        btn.click();
                        return true;
                    }
                }
                return false;
            })()
        """)
        time.sleep(3)

        # If we landed on a search results list, click the first result
        _evaluate(tab, """
            (() => {
                const link = document.querySelector("a[href*='/maps/place/']");
                if (link) { link.click(); return true; }
                return false;
            })()
        """)
        time.sleep(5)

        # Extract place name
        place_name = _evaluate(tab, """
            (() => {
                const all = document.querySelectorAll('h1');
                for (const h of all) {
                    const t = (h.textContent || '').trim();
                    if (t && t !== 'Ergebnisse' && t !== 'Results') return t;
                }
                return null;
            })()
        """)

        # Get current URL
        maps_url = _evaluate(tab, "window.location.href") or ""

        # Extract address from the page
        resolved_address = _evaluate(tab, """
            (() => {
                const btns = document.querySelectorAll('button[aria-label]');
                for (const btn of btns) {
                    const label = btn.getAttribute('aria-label') || '';
                    if (label.startsWith('Adresse:') || label.startsWith('Address:')) {
                        return label.replace('Adresse: ', '').replace('Address: ', '').trim();
                    }
                }
                return null;
            })()
        """)

        # Extract all busyness aria-labels
        labels = _evaluate(tab, """
            (() => {
                const els = document.querySelectorAll('[aria-label]');
                const out = [];
                for (const el of els) {
                    const l = el.getAttribute('aria-label');
                    if (l && (l.includes('ausgelastet') || l.includes('busy') ||
                              l.includes('Derzeit') || l.includes('Currently')))
                        out.push(l);
                }
                return out;
            })()
        """) or []

    finally:
        if tab is not None:
            try:
                tab.stop()
            except Exception:
                pass
            try:
                browser.close_tab(tab)
            except Exception:
                pass

    parsed = _parse_labels(labels)

    return {
        "name": place_name,
        "address": resolved_address or address,
        "maps_url": maps_url,
        "live": parsed["live"],
        "popular_times": parsed["popular_times"],
    }
