#!/usr/bin/env python3
"""Smoke test for MCP HTTP bridge and OpenAI integration.

This script tests:
1. MCP HTTP server health
2. MCP tools/list endpoint
3. MCP tools/call endpoint (weather_get)
4. Intent classification
"""

import asyncio
import json
import sys

import httpx


async def test_mcp_health(base_url: str) -> bool:
    """Test MCP server health endpoint."""
    print("🔍 Testing MCP health endpoint...")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{base_url}/health", timeout=5.0)
            response.raise_for_status()
            data = response.json()
            print(f"✅ Health check passed: {data}")
            return True
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False


async def test_mcp_tools_list(base_url: str) -> bool:
    """Test MCP tools/list endpoint."""
    print("\n🔍 Testing MCP tools/list...")
    try:
        request_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/mcp",
                json=request_payload,
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            
            if "error" in data:
                print(f"❌ Tools list failed: {data['error']}")
                return False
            
            tools = data.get("result", {}).get("tools", [])
            print(f"✅ Tools list returned {len(tools)} tools:")
            for tool in tools:
                print(f"   - {tool['name']}: {tool.get('description', 'No description')}")
            
            # Verify expected tools
            tool_names = [t["name"] for t in tools]
            expected = ["weather_get", "fx_convert"]
            missing = [t for t in expected if t not in tool_names]
            if missing:
                print(f"⚠️  Missing expected tools: {missing}")
            
            return len(tools) > 0
            
    except Exception as e:
        print(f"❌ Tools list failed: {e}")
        return False


async def test_mcp_tool_call(base_url: str) -> bool:
    """Test MCP tools/call endpoint with weather_get."""
    print("\n🔍 Testing MCP tools/call (weather_get)...")
    try:
        request_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "weather_get",
                "arguments": {
                    "city": "London",
                    "country": "GB",
                },
            },
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/mcp",
                json=request_payload,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            
            if "error" in data:
                print(f"❌ Tool call failed: {data['error']}")
                return False
            
            result = data.get("result", {})
            content = result.get("content", [])
            
            if content and content[0].get("type") == "text":
                tool_result = json.loads(content[0]["text"])
                print("✅ Tool call succeeded:")
                print(f"   Location: {tool_result.get('location')}")
                print(f"   Current: {tool_result.get('current')}")
                return True
            else:
                print(f"❌ Unexpected result format: {result}")
                return False
                
    except Exception as e:
        print(f"❌ Tool call failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_intent_classifier() -> bool:
    """Test intent classification."""
    print("\n🔍 Testing intent classifier...")
    try:
        from app.llm.intent_classifier import classify_intent, IntentType
        
        test_cases = [
            ("What's the weather in Paris?", IntentType.TOOL_MODE),
            ("Show me the weather in London", IntentType.TOOL_MODE),
            ("Convert 100 USD to EUR", IntentType.TOOL_MODE),
            ("Create a task for tomorrow", IntentType.OPS_MODE),
            ("Add a note about the meeting", IntentType.OPS_MODE),
            ("List all tasks", IntentType.OPS_MODE),
        ]
        
        all_passed = True
        for message, expected in test_cases:
            result = classify_intent(message)
            status = "✅" if result == expected else "❌"
            print(f"   {status} '{message}' -> {result.value} (expected: {expected.value})")
            if result != expected:
                all_passed = False
        
        if all_passed:
            print("✅ All intent classification tests passed")
        else:
            print("⚠️  Some intent classification tests failed")
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Intent classifier test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all smoke tests."""
    print("=" * 60)
    print("MCP Integration Smoke Tests")
    print("=" * 60)
    
    # Determine base URL (can be overridden via CLI)
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"
    print(f"🌐 Testing against: {base_url}\n")
    
    results = []
    
    # Test 1: Health check
    results.append(await test_mcp_health(base_url))
    
    # Test 2: Tools list
    results.append(await test_mcp_tools_list(base_url))
    
    # Test 3: Tool call
    results.append(await test_mcp_tool_call(base_url))
    
    # Test 4: Intent classifier
    results.append(test_intent_classifier())
    
    # Summary
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ All smoke tests passed!")
        return 0
    else:
        print(f"❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
