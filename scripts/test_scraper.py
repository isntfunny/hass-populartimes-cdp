#!/usr/bin/env python3
"""Standalone test for the Popular Times scraper.

Usage:
    python3 scripts/test_scraper.py "Hallenbad Gelnhausen"
    python3 scripts/test_scraper.py "JYSK Gelnhausen, Freigerichter Str. 4a, 63571 Gelnhausen" \\
        --cdp http://192.168.178.5:9222
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# Stub the package's relative import (.const) so we don't need HA installed.
ROOT = Path(__file__).resolve().parent.parent
SCRAPER_DIR = ROOT / "custom_components" / "populartimes"

const_spec = importlib.util.spec_from_file_location(
    "populartimes_const", SCRAPER_DIR / "const.py"
)
const_mod = importlib.util.module_from_spec(const_spec)
const_spec.loader.exec_module(const_mod)

# Build a fake parent package so `from .const import DAYS_EN` works.
import types
pkg = types.ModuleType("populartimes")
pkg.__path__ = [str(SCRAPER_DIR)]
sys.modules["populartimes"] = pkg
sys.modules["populartimes.const"] = const_mod

scraper_spec = importlib.util.spec_from_file_location(
    "populartimes.scraper", SCRAPER_DIR / "scraper.py"
)
scraper = importlib.util.module_from_spec(scraper_spec)
sys.modules["populartimes.scraper"] = scraper
scraper_spec.loader.exec_module(scraper)

ConnectionFailed = scraper.ConnectionFailed
ScraperError = scraper.ScraperError
scrape_popular_times = scraper.scrape_popular_times


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Popular Times scraper")
    parser.add_argument("address", help="Place address to scrape")
    parser.add_argument(
        "--cdp",
        default="http://192.168.178.5:9222",
        help="CDP browser URL (default: %(default)s)",
    )
    args = parser.parse_args()

    print(f"→ Scraping: {args.address}")
    print(f"→ CDP URL:  {args.cdp}\n")

    try:
        result = scrape_popular_times(args.cdp, args.address)
    except ConnectionFailed as err:
        print(f"✗ CDP connection failed: {err}")
        return 2
    except ScraperError as err:
        print(f"✗ Scraper error: {err}")
        return 3
    except Exception as err:
        import traceback
        print(f"✗ Unexpected error: {type(err).__name__}: {err}")
        traceback.print_exc()
        return 4

    print("✓ Scrape completed\n")
    print(f"Name:    {result.get('name')}")
    print(f"Address: {result.get('address')}")
    print(f"URL:     {result.get('maps_url')}")

    live = result.get("live", {})
    print(f"\nLive data: {'YES' if live.get('is_live') else 'NO'}")
    if live.get("is_live"):
        print(f"  Current: {live.get('current_pct')}%")
        print(f"  Usual:   {live.get('usual_pct')}%")

    opening = result.get("opening", {})
    if opening:
        is_open = opening.get("is_open")
        state = "OPEN" if is_open else ("CLOSED" if is_open is False else "UNKNOWN")
        print(f"\nStatus:  {state}")
        if opening.get("status_text"):
            print(f"  Text:  {opening['status_text']}")
        if opening.get("hours"):
            print("  Hours:")
            for day, hours in opening["hours"].items():
                print(f"    {day}: {hours}")

    popular = result.get("popular_times", {})
    days_with_data = sum(1 for h in popular.values() if any(v > 0 for v in h))
    print(f"\nPopular times: data for {days_with_data}/7 days")

    print("\n--- Full JSON ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
