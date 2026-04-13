"""CDP scraper for Google Maps popular times data using pychrome."""

import json
import logging
import re
import time
import urllib.parse
import warnings
from datetime import datetime

import pychrome
import pychrome.tab
import requests
import websocket

from .const import DAYS_EN

_LOGGER = logging.getLogger(__name__)


def _patched_recv_loop(self) -> None:
    """Patched pychrome recv loop tolerant to multi-message WS frames.

    Newer Chrome versions occasionally pack multiple CDP JSON messages into a
    single WebSocket frame, which causes pychrome's stock loop to die with
    "Extra data: ..." and hang all subsequent CDP calls. We use raw_decode to
    consume all JSON objects from the frame and skip malformed messages.
    """
    decoder = json.JSONDecoder()
    while not self._stopped.is_set():
        try:
            self._ws.settimeout(1)
            message_json = self._ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        except (websocket.WebSocketException, OSError):
            if not self._stopped.is_set():
                _LOGGER.error("websocket exception", exc_info=True)
                self._stopped.set()
            return

        messages = []
        idx = 0
        text = message_json.lstrip()
        while idx < len(text):
            try:
                obj, end = decoder.raw_decode(text, idx)
            except json.JSONDecodeError:
                _LOGGER.debug("Skipping malformed CDP message: %r", text[idx:idx + 80])
                break
            messages.append(obj)
            idx = end
            while idx < len(text) and text[idx] in " \t\n\r":
                idx += 1

        for message in messages:
            if "method" in message:
                self.event_queue.put(message)
            elif "id" in message:
                if message["id"] in self.method_results:
                    self.method_results[message["id"]].put(message)
            else:
                warnings.warn("unknown message: %s" % message)


pychrome.tab.Tab._recv_loop = _patched_recv_loop

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


def _list_tabs(cdp_url: str) -> list[dict]:
    """List CDP tabs via /json/list. Filters out non-page targets."""
    resp = requests.get(cdp_url.rstrip("/") + "/json/list", timeout=10)
    resp.raise_for_status()
    return [t for t in resp.json() if t.get("type") == "page"]


def _create_target_tab(cdp_url: str) -> tuple[pychrome.Tab, str]:
    """Create a new tab via Target.createTarget on an anchor tab.

    Modern Chrome (111+) disables /json/new for security. We instead pick any
    existing tab as an anchor and ask it to create a new target via CDP, then
    look the new target up in /json/list to get its WebSocket URL.

    Returns (tab, target_id). Caller must call _close_target_tab when done.
    """
    existing = _list_tabs(cdp_url)
    if not existing:
        raise ConnectionFailed(
            "No existing tabs in CDP browser to anchor on. "
            "The browser must have at least one open page."
        )

    anchor = pychrome.Tab(**existing[0])
    anchor.start()
    try:
        result = anchor.call_method("Target.createTarget", url="about:blank")
        target_id = result.get("targetId")
        if not target_id:
            raise ConnectionFailed(f"Target.createTarget returned no targetId: {result}")
    finally:
        try:
            anchor.stop()
        except Exception:
            pass

    # Find the new target in /json/list to get its webSocketDebuggerUrl
    for _ in range(10):
        for t in _list_tabs(cdp_url):
            if t.get("id") == target_id:
                return pychrome.Tab(**t), target_id
        time.sleep(0.2)

    raise ConnectionFailed(f"New target {target_id} did not appear in /json/list")


def _close_target_tab(cdp_url: str, target_id: str) -> None:
    """Close a target via Target.closeTarget on an anchor tab."""
    try:
        existing = _list_tabs(cdp_url)
        if not existing:
            return
        anchor = pychrome.Tab(**existing[0])
        anchor.start()
        try:
            anchor.call_method("Target.closeTarget", targetId=target_id)
        finally:
            anchor.stop()
    except Exception as err:
        _LOGGER.debug("Failed to close target %s: %s", target_id, err)


def scrape_popular_times(cdp_url: str, address: str) -> dict:
    """Scrape Google Maps for popular times data via pychrome CDP.

    This is a synchronous function — call via asyncio.to_thread() or executor.

    Returns dict with keys: name, address, maps_url, live, popular_times.
    Raises ConnectionFailed or ScraperError on failure.
    """
    tab = None
    target_id = None
    try:
        try:
            tab, target_id = _create_target_tab(cdp_url)
        except ConnectionFailed:
            raise
        except Exception as err:
            raise ConnectionFailed(
                f"Failed to create new CDP target at {cdp_url}: {err}"
            ) from err

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

        # Extract opening status (e.g. "Geöffnet", "Geschlossen · Öffnet um 10:00")
        # Retry up to 2 extra times if the span hasn't rendered yet.
        opening_status = None
        for _attempt in range(3):
            opening_status = _evaluate(tab, """
                (() => {
                    const spans = document.querySelectorAll('span');
                    for (const s of spans) {
                        const t = (s.textContent || '').trim();
                        if (/^(Ge.ffnet|Geschlossen|Open$|Closed)/i.test(t))
                            return t;
                    }
                    return null;
                })()
            """)
            if opening_status is not None:
                break
            _LOGGER.debug("Opening status not found (attempt %d/3), retrying", _attempt + 1)
            time.sleep(1 + _attempt)  # 1s, then 2s

        # Extract opening hours per day from aria-labels
        opening_hours = _evaluate(tab, """
            (() => {
                const out = {};
                const btns = document.querySelectorAll('button[aria-label*="ffnungszeiten kopieren"], button[aria-label*="Copy hours"]');
                for (const btn of btns) {
                    const l = btn.getAttribute('aria-label') || '';
                    const m = l.match(/^(.+?),(.+?),/);
                    if (m) out[m[1].trim()] = m[2].trim();
                }
                return Object.keys(out).length > 0 ? out : null;
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
        if target_id is not None:
            _close_target_tab(cdp_url, target_id)

    parsed = _parse_labels(labels)

    # Determine open/closed from status text
    is_open = None
    if opening_status:
        lower = opening_status.lower()
        if "geöffnet" in lower or "open" == lower:
            is_open = True
        elif "geschlossen" in lower or "closed" in lower:
            is_open = False

    return {
        "name": place_name,
        "address": resolved_address or address,
        "maps_url": maps_url,
        "live": parsed["live"],
        "popular_times": parsed["popular_times"],
        "opening": {
            "is_open": is_open,
            "status_text": opening_status,
            "hours": opening_hours,
        },
    }
