"""Per-client settings, read from environment variables (or Streamlit secrets, which
Streamlit Cloud exposes as environment variables).

For a new client you set these and nothing else in the code changes:
  SAUTI_CLIENT_NAME   the client's name, e.g. "L’Oréal Kenya"
  SAUTI_DEMO          "1" = demo environment (default), "0" = real client deployment
"""
import os

CLIENT_NAME = os.environ.get("SAUTI_CLIENT_NAME", "L’Oréal Kenya")

# Default is demo ON, so a fresh checkout works. A real client deployment sets SAUTI_DEMO=0:
# then no demo data is loaded and the demo banner is hidden.
DEMO_MODE = os.environ.get("SAUTI_DEMO", "1") != "0"

DEMO_BANNER = (
    "🧪 Demo environment. All data here is simulated. Please use test text and test images only, "
    "and do not enter real personal details or photos of yourself or other people. "
    "Anything submitted may be deleted after the demo."
)