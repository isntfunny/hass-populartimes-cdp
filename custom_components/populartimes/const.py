"""Constants for the Popular Times integration."""

DOMAIN = "populartimes"

CONF_ADDRESS = "address"
CONF_CDP_URL = "cdp_url"
CONF_SKIP_LIVE_CHECK = "skip_live_check"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_CDP_URL = "http://192.168.178.5:9222"
DEFAULT_SCAN_INTERVAL = 10  # 10 minutes
MIN_SCAN_INTERVAL = 2
MAX_SCAN_INTERVAL = 60

DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
