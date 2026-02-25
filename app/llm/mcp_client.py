import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, List


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: Dict[str, Any]


class McpClient:
    def __init__(self, cmd: List[str]) -> None:
        self._cmd = cmd
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._next_id = 1

    async def start(self) -> None:
        if self._proc and self._proc.returncode is None:
            return

        self._proc = await asyncio.create_subprocess_exec(
            *self._cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await self._rpc("initialize", {})

    async def close(self) -> None:
        if not self._proc:
            return
        if self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._proc = None

    async def list_tools(self) -> List[McpTool]:
        res = await self._rpc("tools/list", {})
        tools = res.get("tools", [])
        return [McpTool(**t) for t in tools]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        res = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        return res.get("content", {})

    async def _rpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            await self.start()
            assert self._proc and self._proc.stdin and self._proc.stdout

            req_id = str(self._next_id)
            self._next_id += 1

            payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self._proc.stdin.drain()

            line = await self._proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed stdout")

            resp = json.loads(line.decode("utf-8", errors="replace"))
            if resp.get("id") != req_id:
                raise RuntimeError(f"Unexpected response id: {resp.get('id')} != {req_id}")

            if "error" in resp and resp["error"] is not None:
                raise RuntimeError(f"MCP error: {resp['error']}")

            return resp.get("result") or {}
