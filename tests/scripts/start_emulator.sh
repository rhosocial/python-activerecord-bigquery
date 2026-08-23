#!/bin/bash
# Start BigQuery emulator (goccy/bigquery-emulator) for local testing
# Usage: bash tests/scripts/start_emulator.sh

set -e

echo "Starting BigQuery emulator (goccy/bigquery-emulator)..."
echo "Project: test | Ports: 9050 (REST), 9060 (gRPC)"

docker run -d \
  --name bigquery-emulator \
  -p 9050:9050 \
  -p 9060:9060 \
  ghcr.io/goccy/bigquery-emulator:latest \
  --project=test --data-from-yaml=/work/test.yaml --dataset=test_dataset || echo "Container may already exist; check with 'docker ps'"

echo "Emulator started. Python clients should use:"
echo "  project='test'"
echo "  credentials=AnonymousCredentials()"
echo "  client_options=ClientOptions(api_endpoint='http://localhost:9050')"
