#!/bin/bash
# Quick reference commands for testing MCP integration

set -e

BASE_URL="${1:-http://localhost:8001}"

echo "================================================"
echo "MCP Integration - Quick Test Commands"
echo "Base URL: $BASE_URL"
echo "================================================"

echo -e "\n1️⃣  Health Check"
echo "Command: curl $BASE_URL/health"
curl -s "$BASE_URL/health" | jq .

echo -e "\n2️⃣  List Available Tools"
echo "Command: curl -X POST $BASE_URL/mcp -d '{...}'"
curl -s -X POST "$BASE_URL/mcp" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | jq .

echo -e "\n3️⃣  Call weather_get Tool (London)"
echo "Command: curl -X POST $BASE_URL/mcp -d '{...}'"
curl -s -X POST "$BASE_URL/mcp" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "weather_get",
      "arguments": {
        "city": "London",
        "country": "GB"
      }
    }
  }' | jq .

echo -e "\n4️⃣  Call weather_get Tool (New York)"
echo "Command: curl -X POST $BASE_URL/mcp -d '{...}'"
curl -s -X POST "$BASE_URL/mcp" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "weather_get",
      "arguments": {
        "city": "New York",
        "country": "US"
      }
    }
  }' | jq .

echo -e "\n✅ All test commands completed!"
echo -e "\nTo run Python smoke tests:"
echo "  python scripts/smoke_test_mcp.py $BASE_URL"
