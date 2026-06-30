"""
Application-wide settings.
"""

import os

# Directory where uploaded files are stored
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/app/uploads")

# Directory where generated Excel reports are stored
REPORTS_DIR = os.environ.get("REPORTS_DIR", "/app/generated_reports")

# Maximum upload size: 50 MB
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

# Ensure runtime directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
