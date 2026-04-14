# Changelog

All notable changes to this project will be documented in this file.

The format is intentionally simple so entries can also be reused in GitHub and HACS release notes.

## [1.1.3] - 2026-04-14

### Fixed
- Retry opening-status extraction up to three times so the sensor no longer falls back to `unknown` when the status span has not rendered yet on slower Maps loads.
- Close the orphan CDP target when the newly created tab does not appear in `/json/list`, preventing stale `about:blank` tabs from piling up in the browser.

### Added
- Ship a HACS brand icon and logo so the integration has a custom tile in the HACS store.

## [1.1.2] - 2026-04-07

### Fixed
- Fix scraping completely failing on `cloakhq/cloakbrowser` v0.3.20+ (and any modern Chrome) where the `/json/new` HTTP endpoint is disabled. The scraper now creates new browser tabs via the CDP `Target.createTarget` command through an anchor tab, the same approach Playwright uses internally.
- Patch pychrome's WebSocket receive loop to tolerate multi-message frames sent by newer Chrome versions, which previously crashed the background thread with `Extra data` JSON errors.

### Added
- Add a standalone `scripts/test_scraper.py` test script that verifies scraping works against a CDP browser without requiring a Home Assistant install.

## [1.1.1] - 2026-04-05

### Added
- No user-facing features added in this release.

### Changed
- Change the `current` popularity sensor to only report a value when Google Maps provides live popularity data.

### Fixed
- Prevent the `current` popularity sensor from falling back to the historical `usual` value when live data is unavailable.

## [1.1.0] - 2026-04-05

### Added
- Add a manual refresh button entity for each configured Popular Times place.
- Add an automatic polling switch entity for each configured place.
- Add an event entity for each configured place.
- Add explicit poll success event types:
  - `automatic_poll_completed`
  - `manual_poll_completed`
- Add explicit poll failure event types:
  - `automatic_poll_failed`
  - `manual_poll_failed`
- Add shared device metadata helper so all entities attach to the same Home Assistant device.

### Changed
- Extend the integration from sensor/binary sensor only to also expose button, switch, and event platforms.
- Keep the existing `DataUpdateCoordinator` as the single fetch and cache path.
- Add coordinator-managed polling state and last poll metadata.
- Improve entity naming with Home Assistant translation keys for the new entities.
- Update README documentation for the new entities and poll behavior.

### Fixed
- Align manual refresh handling with Home Assistant 2026.3 coordinator patterns.
- Ensure event entities write their state after triggering events.
- Keep event entities available for poll failure reporting instead of coupling availability to coordinator success state.
