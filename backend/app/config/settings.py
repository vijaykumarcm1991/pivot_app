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
