#!/bin/bash
# docker compose down -v
docker compose down
# docker compose build --no-cache
docker compose build
docker compose up -d
docker compose ps
