#!/bin/bash
set -e
cd "$(dirname "$0")"

# The user-directory CSVs are bind-mounted read-only into the container.
# Create header-only placeholders when they are missing so Docker never
# has to (it would create root-owned directories with these names).
for f in Users.csv DistributionLists.csv; do
  if [ -d "$f" ]; then
    echo "ERROR: ./$f is a directory (left over from an earlier docker run)." >&2
    echo "       Remove it (sudo rmdir ./$f) and put the CSV file there instead." >&2
    exit 1
  fi
done
[ -f Users.csv ] || printf '"DisplayName","PrimarySmtpAddress","Alias"\r\n' > Users.csv
[ -f DistributionLists.csv ] || printf '"DisplayName","Alias","PrimarySmtpAddress","ManagedBy"\r\n' > DistributionLists.csv

# docker compose down -v
docker compose down
# docker compose build --no-cache
docker compose build
docker compose up -d
docker compose ps
