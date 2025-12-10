import asyncio
import json
import time
from typing import Any, Dict
import sqlite3

from fastapi import WebSocket
from websockets.server import WebSocketServerProtocol

from database import DB_PATH

# WebSocket connection pools and pending RPC responses
node_websockets: Dict[int, WebSocketServerProtocol] = {}
pending_responses: Dict[int, Dict[int, asyncio.Future]] = {}


async def wait_for_response(
    websocket: WebSocketServerProtocol, node_id: int, rpc_id: int, timeout: float = 30.0
) -> Any:
    """Wait for a JSON-RPC response tied to node_id + rpc_id."""
    future: asyncio.Future = asyncio.Future()

    if node_id not in pending_responses:
        pending_responses[node_id] = {}
    pending_responses[node_id][rpc_id] = future

    try:
        response = await asyncio.wait_for(future, timeout=timeout)

        if isinstance(response, dict) and "error" in response:
            error_info = response["error"]
            if isinstance(error_info, dict):
                code = error_info.get("code", "Unknown")
                message = error_info.get("message", "Unknown error")
                raise Exception(f"RPC Error {code}: {message}")
            raise Exception(f"RPC Error: {error_info}")

        if isinstance(response, dict):
            return response.get("result")
        return None
    finally:
        if node_id in pending_responses:
            pending_responses[node_id].pop(rpc_id, None)
            if not pending_responses[node_id]:
                pending_responses.pop(node_id, None)


async def handle_jsonrpc_response(message: dict, node_id: int | None = None) -> None:
    """Handle JSON-RPC response and resolve waiting futures."""
    if isinstance(message, dict) and "id" in message and node_id is not None:
        rpc_id = message["id"]
        node_pending = pending_responses.get(node_id, {})
        if rpc_id in node_pending:
            future = node_pending[rpc_id]
            if not future.done():
                future.set_result(message)


async def notify_node_config_update(node_id: int) -> None:
    """Notify node to refresh configuration."""
    if node_id in node_websockets:
        websocket = node_websockets[node_id]
        notification = {"jsonrpc": "2.0", "method": "node.update_config", "params": {}}
        try:
            await websocket.send_text(json.dumps(notification))
        except Exception as exc:
            print(f"通知Node {node_id} 更新配置失败: {exc}")


async def notify_node_start_teleop_group(node_id: int, group_id: int) -> None:
    """Notify node to start a teleop group."""
    if node_id in node_websockets:
        websocket = node_websockets[node_id]
        notification = {
            "jsonrpc": "2.0",
            "method": "node.start_teleop_group",
            "params": {"id": group_id},
        }

        try:
            if websocket.state.name != "CLOSED":
                await websocket.send_text(json.dumps(notification))
        except Exception as exc:
            print(f"通知Node {node_id} 启动遥操组 {group_id} 失败: {exc}")


async def notify_node_stop_teleop_group(node_id: int, group_id: int) -> None:
    """Notify node to stop a teleop group."""
    if node_id in node_websockets:
        websocket = node_websockets[node_id]
        notification = {
            "jsonrpc": "2.0",
            "method": "node.stop_teleop_group",
            "params": {"id": group_id},
        }

        try:
            if websocket.state.name != "CLOSED":
                await websocket.send_text(json.dumps(notification))
        except Exception as exc:
            print(f"通知Node {node_id} 停止遥操组 {group_id} 失败: {exc}")


async def call_node_rpc(node_id: int, method: str, params: Any = None, timeout: float = 30.0) -> Any:
    """Send an RPC request to a node and return the result."""
    if node_id not in node_websockets:
        raise Exception("Node not connected")

    websocket = node_websockets[node_id]
    rpc_id = int(time.time() * 1000)
    rpc_request = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": rpc_id,
    }

    await websocket.send_text(json.dumps(rpc_request))
    return await wait_for_response(websocket, node_id, rpc_id, timeout=timeout)


async def handle_jsonrpc_request(
    request: dict, websocket: WebSocket, connection_context: dict
) -> dict:
    """Handle JSON-RPC request coming from node."""
    rpc_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    response: Dict[str, Any] = {"jsonrpc": "2.0", "id": rpc_id}

    try:
        if method == "backend.register":
            result = await handle_node_register(params, websocket)
            response["result"] = result
            if isinstance(result, dict) and "id" in result:
                connection_context["node_id"] = result["id"]
                if connection_context["node_id"]:
                    node_websockets[connection_context["node_id"]] = websocket
        else:
            response["error"] = {"code": -32601, "message": "Method not found"}
    except Exception as exc:
        response["error"] = {"code": -32603, "message": str(exc)}

    return response


async def handle_node_register(params: dict, websocket: WebSocket) -> dict:
    """Handle node register RPC from node -> backend."""
    node_uuid = params.get("uuid")
    if not node_uuid:
        raise Exception("Missing uuid parameter")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id FROM nodes WHERE uuid = ?", (node_uuid,))
        result = cursor.fetchone()

        if result:
            node_id = result[0]
        else:
            cursor.execute("INSERT INTO nodes (uuid) VALUES (?)", (node_uuid,))
            node_id = cursor.lastrowid

        conn.commit()
        node_websockets[node_id] = websocket
        return {"id": node_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def handle_node_test_device(params: dict) -> int:
    """Handle device test RPC."""
    category = params.get("category")
    type_name = params.get("type")
    config = params.get("config")
    print(f"Testing device: {category}.{type_name} with config {config}")
    await asyncio.sleep(3)
    return 1
