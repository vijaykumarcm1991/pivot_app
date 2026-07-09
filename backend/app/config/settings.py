"""
Application-wide settings — values that come from environment variables
and on-disk defaults. The runtime-user-configurable values live in the
`app_settings` SQLite row (see `app.models.app_settings`).
"""
import os


# Directory where uploaded files are stored
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/app/uploads")

# Directory where generated Excel reports are stored
REPORTS_DIR = os.environ.get("REPORTS_DIR", "/app/generated_reports")

# Directory where application log files are stored
LOG_DIR = os.environ.get("LOG_DIR", "/app/logs")

# Paths to the directory CSVs — both are mounted into the container
# from the host by docker-compose.yml.  The user drops fresh files
# on the host whenever the company directory changes and the email
# composer's typeahead picks them up on the next request (mtime-
# based auto-reload).
#
#   Users.csv                — one row per individual user / mailbox
#   DistributionLists.csv    — one row per group / distribution list
USERS_CSV_PATH = (
    os.environ.get("USERS_CSV_PATH", "/app/Users.csv").strip()
    or "/app/Users.csv"
)
DISTRIBUTION_LISTS_CSV_PATH = (
    os.environ.get("DISTRIBUTION_LISTS_CSV_PATH", "/app/DistributionLists.csv").strip()
    or "/app/DistributionLists.csv"
)

# Maximum upload size: 50 MB (default; can be lowered at runtime via Settings)
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Allowed file extensions
ALLOWED_EXTENSIONS = {".xlsx", ".csv"}

# Number of preview rows shown in the UI
PREVIEW_ROW_LIMIT = 20

# Data size limits for processing
MAX_ROWS_ALLOWED = 100000  # Maximum rows for dataset processing
MAX_COLUMNS_ALLOWED = 200   # Maximum columns for dataset processing
MAX_PIVOT_RESULT_ROWS = 10000  # Maximum rows a pivot can return

# Memory limits for pivot operations (in MB)
MAX_PIVOT_MEMORY_MB = 500  # 500 MB max for pivot computations

# Application name (the Settings page can override this at runtime; the
# default here is used as a fallback for templates and emails).
APP_NAME = "Pivot App"

# Ensure runtime directories exist
for d in (UPLOAD_DIR, REPORTS_DIR, LOG_DIR):
    os.makedirs(d, exist_ok=True)

# The directory CSVs are optional — the container starts fine
# without either of them (the typeahead just shows no suggestions
# and the Settings page tells the user how to add the files).
# We create the parent directories so a fresh mount works at
# runtime without the user having to mkdir first.
for _p in (USERS_CSV_PATH, DISTRIBUTION_LISTS_CSV_PATH):
    _d = os.path.dirname(_p)
    if _d and not os.path.exists(_d):
        try:
            os.makedirs(_d, exist_ok=True)
        except OSError:
            # The host mount may be read-only; that's fine — the
            # service can still read an existing file from the
            # mount.
            pass
