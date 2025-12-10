from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from typing import Any, Dict, List, Optional
import asyncio
import json
import logging
import sqlite3
import time

from database import DB_PATH, get_node_devices, get_node_teleop_groups, init_tables
from rpc import (
    handle_jsonrpc_request,
    handle_jsonrpc_response,
    node_websockets,
    notify_node_config_update,
    notify_node_start_teleop_group,
    notify_node_stop_teleop_group,
    call_node_rpc,
    wait_for_response,
)
from schemas import (
    DeviceCreate,
    DeviceResponse,
    DeviceTestRequest,
    DeviceUpdate,
    NodeRegisterRequest,
    NodeRegisterResponse,
    NodeResponse,
    TeleopGroupCreate,
    TeleopGroupResponse,
    TeleopGroupUpdate,
    VRCreate,
    VRResponse,
    VRUpdate,
    RPCCallResponse,
    NodeRPCCallRequest,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

app = FastAPI()

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 节点相关API路由
@app.post("/api/node", response_model=NodeRegisterResponse, status_code=201)
async def register_node(request: NodeRegisterRequest):
    """节点注册API"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 检查节点是否已存在
        cursor.execute("SELECT id FROM nodes WHERE uuid = ?", (request.uuid,))
        result = cursor.fetchone()
        
        if result:
            node_id = result[0]
        else:
            # 创建新节点
            cursor.execute("INSERT INTO nodes (uuid) VALUES (?)", (request.uuid,))
            node_id = cursor.lastrowid
            
        conn.commit()
        
        # 获取该节点的设备和遥操组配置
        devices = get_node_devices(node_id)
        teleop_groups = get_node_teleop_groups(node_id)
        
        return NodeRegisterResponse(
            id=node_id,
            devices=devices,
            teleop_groups=teleop_groups
        )
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
@app.get("/api/nodes", response_model=List[NodeResponse])
async def get_nodes(uuid: Optional[str] = None):
    """获取节点列表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if uuid:
        cursor.execute(
            "SELECT id, uuid,status, created_at, updated_at FROM nodes WHERE uuid = ?",
            (uuid,)
        )
    else:
        cursor.execute("SELECT id, uuid,status, created_at, updated_at FROM nodes")
    
    nodes = []
    for row in cursor.fetchall():
        nodes.append(NodeResponse(
            id=row[0],
            uuid=row[1],
            status=row[2],
            created_at=row[3],
            updated_at=row[4]
        ))
        
    conn.close()
    return nodes


@app.get("/api/nodes/{node_id}/rpc")
async def get_node_rpc_methods(node_id: int) -> Dict[str, Any]:
    """获取指定节点暴露的RPC方法列表和参数信息"""
    if node_id not in node_websockets:
        raise HTTPException(status_code=404, detail="Node not connected")

    try:
        methods = await call_node_rpc(node_id, "node.get_rpc_methods", {})
        if not (isinstance(methods, dict) and "methods" in methods):
            raise HTTPException(status_code=500, detail="Invalid method list from node")
        return {"methods": methods.get("methods")}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/nodes/{node_id}/rpc", response_model=RPCCallResponse)
async def call_node_rpc_method(node_id: int, request: NodeRPCCallRequest) -> Dict[str, Any]:
    """向指定节点转发RPC调用"""
    if node_id not in node_websockets:
        raise HTTPException(status_code=404, detail="Node not connected")

    try:
        result = await call_node_rpc(node_id, request.method, request.params or {})
        return {"result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/nodes/{node_id}", response_model=NodeResponse)
async def get_node(node_id: int):
    """获取单个节点详情"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, uuid,status, created_at, updated_at FROM nodes WHERE id = ?",
        (node_id,)
    )
    
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Node not found")
        
    node = NodeResponse(
        id=row[0],
        uuid=row[1],
        status=row[2],
        created_at=row[3],
        updated_at=row[4]
    )
        
    conn.close()
    return node

# 设备相关API路由
@app.get("/api/device/categories")
async def get_device_categories(node_id: int = Query(...)):
    """获取所有设备分类"""
    # 通过RPC从Node获取设备类型信息
    if node_id not in node_websockets:
        raise HTTPException(status_code=404, detail="Node not connected")
        
    try:
        # 直接发送RPC请求，不使用WebSocketRPC
        websocket = node_websockets[node_id]
        rpc_id = int(time.time() * 1000)
        rpc_request = {
            "jsonrpc": "2.0",
            "method": "node.get_device_types",
            "params": {},
            "id": rpc_id
        }
        print(f"asd{json.dumps(rpc_request)}")
        # 发送请求
        await websocket.send_text(json.dumps(rpc_request))
        print("发送成功")
        
        # 等待并处理响应
        device_types_info = await wait_for_response(websocket, node_id, rpc_id)
        print(device_types_info)
        categories = list(device_types_info.keys())
        return categories
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/device/types")
async def get_device_types_info(node_id: int = Query(...)):
    """获取所有设备类型及对应type_info字典"""
    # 通过RPC从Node获取设备类型信息
    if node_id not in node_websockets:
        raise HTTPException(status_code=404, detail="Node not connected")
        
    try:
        # 直接发送RPC请求，不使用WebSocketRPC
        websocket = node_websockets[node_id]
        rpc_id = int(time.time() * 1000)
        rpc_request = {
            "jsonrpc": "2.0",
            "method": "node.get_device_types",
            "params": {},
            "id": rpc_id
        }
        
        # 发送请求
        await websocket.send_text(json.dumps(rpc_request))
        
        # 等待并处理响应
        device_types_info = await wait_for_response(websocket, node_id, rpc_id)
        return device_types_info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/devices", response_model=List[DeviceResponse])
async def get_devices(node_id: Optional[int] = Query(None)):
    """获取所有设备列表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if node_id is not None:
        cursor.execute(
            """SELECT id, node_id, name, description, category, type, config, status, 
                      created_at, updated_at FROM devices WHERE node_id = ?""",
            (node_id,)
        )
    else:
        cursor.execute(
            """SELECT id, node_id, name, description, category, type, config, status, 
                      created_at, updated_at FROM devices"""
        )
    
    devices = []
    for row in cursor.fetchall():
        try:
            config_data = json.loads(row[6]) if isinstance(row[6], str) else row[6]
        except:
            config_data = {}
            
        devices.append(DeviceResponse(
            id=row[0],
            node_id=row[1],
            name=row[2],
            description=row[3],
            category=row[4],
            type=row[5],
            config=config_data,
            status=row[7] or 0,
            created_at=row[8],
            updated_at=row[9]
        ))
        
    conn.close()
    return devices

@app.get("/api/devices/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: int):
    """获取单个设备详情"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        """SELECT id, node_id, name, description, category, type, config, status, 
                  created_at, updated_at FROM devices WHERE id = ?""",
        (device_id,)
    )
    
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Device not found")
        
    try:
        config_data = json.loads(row[6]) if isinstance(row[6], str) else row[6]
    except:
        config_data = {}
        
    device = DeviceResponse(
        id=row[0],
        node_id=row[1],
        name=row[2],
        description=row[3],
        category=row[4],
        type=row[5],
        config=config_data,
        status=row[7] or 0,
        created_at=row[8],
        updated_at=row[9]
    )
        
    conn.close()
    return device

@app.post("/api/devices", status_code=201)
async def create_device(device: DeviceCreate):
    """新增设备"""
    # 验证节点是否存在且连接
    if device.node_id not in node_websockets:
        raise HTTPException(status_code=400, detail="Node not connected")
    
    # 对config进行测试，test成功才能创建设备
    # try:
    #     # 直接发送RPC请求，不使用WebSocketRPC
    #     websocket = node_websockets[device.node_id]
    #     rpc_id = int(time.time() * 1000)
    #     rpc_request = {
    #         "jsonrpc": "2.0",
    #         "method": "node.test_device",
    #         "params": {
    #             "category": device.category,
    #             "type": device.type,
    #             "config": device.config
    #         },
    #         "id": rpc_id
    #     }
        
    #     # 发送请求
    #     await websocket.send_text(json.dumps(rpc_request))
        
    #     # 等待并处理响应
    #     test_result = await wait_for_response(websocket, node_id, rpc_id)
        
    #     # 检查测试结果，确保test_result是字典类型
    #     if not isinstance(test_result, dict) or test_result.get("success") is not True:
    #         error_msg = test_result.get("error", "Device test failed") if isinstance(test_result, dict) else "Device test failed"
    #         raise HTTPException(status_code=400, detail=error_msg)
    # except asyncio.TimeoutError:
    #     raise HTTPException(status_code=504, detail="Device test timeout")
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=f"Device test error: {str(e)}")
    
    # 在数据库中创建设备
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            """INSERT INTO devices (node_id, name, description, category, type, config) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (device.node_id, device.name, device.description, device.category, 
             device.type, json.dumps(device.config))
        )
        device_id = cursor.lastrowid
        conn.commit()
        
        # 通知对应的Node更新配置
        await notify_node_config_update(device.node_id)
        
        # 返回标准化的响应
        return {
            "message": "设备已添加", 
            "id": device_id,
            "device_id": device_id
        }
        
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"Database constraint error: {str(e)}")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.put("/api/devices/{device_id}")
async def update_device(device_id: int, device: DeviceUpdate):
    """更新设备"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 检查设备是否存在
        cursor.execute("SELECT id, node_id FROM devices WHERE id = ?", (device_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Device not found")
            
        node_id = row[1]
        
        # # 对config进行测试，test成功才能更新设备
        # if node_id not in node_websockets:
        #     raise HTTPException(status_code=400, detail="Node not connected")
        
        # try:
        #     # 直接发送RPC请求，不使用WebSocketRPC
        #     websocket = node_websockets[node_id]
        #     rpc_id = int(time.time() * 1000)
        #     rpc_request = {
        #         "jsonrpc": "2.0",
        #         "method": "node.test_device",
        #         "params": {
        #             "category": device.category,
        #             "type": device.type,
        #             "config": device.config
        #         },
        #         "id": rpc_id
        #     }
            
        #     # 发送请求
        #     await websocket.send_text(json.dumps(rpc_request))
            
        #     # 等待并处理响应
        #     test_result = await wait_for_response(websocket, node_id, rpc_id)
            
        #     # 检查测试结果，确保test_result是字典类型
        #     if not isinstance(test_result, dict) or test_result.get("success") is not True:
        #         raise HTTPException(status_code=400, detail="Device test failed")
        # except Exception as e:
        #     raise HTTPException(status_code=500, detail=f"Device test error: {str(e)}")
        
        # 更新设备信息
        cursor.execute(
            """UPDATE devices 
               SET name = ?, description = ?, category = ?, type = ?, config = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (device.name, device.description, device.category, device.type, 
             json.dumps(device.config), device_id)
        )
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Device not found")
            
        conn.commit()
        
        # 通知对应的Node更新配置
        await notify_node_config_update(node_id)
        
        return {"message": "设备已更新"}
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.delete("/api/devices/{device_id}")
async def delete_device(device_id: int):
    """删除设备"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 检查设备是否存在并获取node_id
        cursor.execute("SELECT id, node_id FROM devices WHERE id = ?", (device_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Device not found")
            
        node_id = row[1]
        
        # 删除设备
        cursor.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Device not found")
            
        conn.commit()
        
        # 通知对应的Node更新配置
        await notify_node_config_update(node_id)
        
        return {"message": "设备已删除"}
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/devices/test", description="测试设备连接")
async def test_device_connection(device_test_request: DeviceTestRequest):
    """
    测试设备连接
    
    该端点用于测试指定设备是否能成功连接。需要提供节点ID、设备类别、设备类型和设备配置参数。
    
    示例请求体:
    {
        "node_id": 1,
        "category": "robot", 
        "type": "RealMan",
        "config": {
            "ip": "192.168.1.100",
            "port": 8080
        }
    }
    """
    node_id = device_test_request.node_id
    category = device_test_request.category
    type_name = device_test_request.type
    config = device_test_request.config
    # 验证节点是否存在且连接
    if node_id not in node_websockets:
        raise HTTPException(status_code=400, detail="Node not connected")
    
    try:
        # 直接发送RPC请求，不使用WebSocketRPC
        websocket = node_websockets[node_id]
        rpc_id = int(time.time() * 1000)
        rpc_request = {
            "jsonrpc": "2.0",
            "method": "node.test_device",
            "params": {
                "category": category,
                "type": type_name,
                "config": config
            },
            "id": rpc_id
        }
        
        # 发送请求
        await websocket.send_text(json.dumps(rpc_request))
        
        # 等待并处理响应
        test_result = await wait_for_response(websocket, node_id, rpc_id)
        
        # 检查测试结果，确保test_result是字典类型
        if not isinstance(test_result, dict) or test_result.get("success") is not True:
            raise HTTPException(status_code=400, detail="Device test failed")
            
        return test_result
        
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Device test timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Device test error: {str(e)}")

# 遥操组相关API路由
@app.get("/api/teleop-groups/types")
async def get_teleop_group_types_info(node_id: int = Query(...)):
    """获取遥操组的所有类型和对应的need_config"""
    # 通过RPC从Node获取遥操组类型信息
    if node_id not in node_websockets:
        raise HTTPException(status_code=404, detail="Node not connected")
        
    try:
        # 直接发送RPC请求，不使用WebSocketRPC
        websocket = node_websockets[node_id]
        rpc_id = int(time.time() * 1000)
        rpc_request = {
            "jsonrpc": "2.0",
            "method": "node.get_teleop_group_types",
            "params": {},
            "id": rpc_id
        }
        
        # 发送请求
        await websocket.send_text(json.dumps(rpc_request))
        
        # 等待并处理响应
        teleop_group_types_info = await wait_for_response(websocket, node_id, rpc_id)
        return teleop_group_types_info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/teleop-groups", response_model=List[TeleopGroupResponse])
async def get_teleop_groups(
    name: Optional[str] = Query(None),
    device_id: Optional[int] = Query(None),
    node_id: Optional[int] = Query(None)
):
    """获取所有遥操作组列表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 构造查询语句
    query = """SELECT id, node_id, name, description, type, config, status,capture_status, 
                      created_at, updated_at FROM teleop_groups"""
    params = []
    
    conditions = []
    if name:
        conditions.append("name LIKE ?")
        params.append(f"%{name}%")
    if node_id is not None:
        conditions.append("node_id = ?")
        params.append(node_id)
    if device_id is not None:
        conditions.append("config LIKE ?")
        params.append(f"%{device_id}%")
        
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
        
    query += " ORDER BY id"
    
    cursor.execute(query, params)
    
    groups = []
    for row in cursor.fetchall():
        try:
            config_data = json.loads(row[5]) if isinstance(row[5], str) else row[5]
            # 确保config是列表类型
            if not isinstance(config_data, list):
                config_data = []
        except:
            config_data = []
            
        groups.append(TeleopGroupResponse(
            id=row[0],
            node_id=row[1],
            name=row[2],
            description=row[3],
            type=row[4],
            config=config_data,
            status=row[6],
            capture_status=row[7],
            created_at=row[8],
            updated_at=row[9]
        ))
        
    conn.close()
    return groups

@app.get("/api/teleop-groups/{id}", response_model=TeleopGroupResponse)
async def get_teleop_group(id: int):
    """获取单个遥操组详情"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        """SELECT id, node_id, name, description, type, config, status,capture_status, 
                  created_at, updated_at FROM teleop_groups WHERE id = ?""",
        (id,)
    )
    
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Teleop group not found")
        
    try:
        config_data = json.loads(row[5]) if isinstance(row[5], str) else row[5]
        # 确保config是列表类型
        if not isinstance(config_data, list):
            config_data = []
    except:
        config_data = []
        
    teleop_group = TeleopGroupResponse(
        id=row[0],
        node_id=row[1],
        name=row[2],
        description=row[3],
        type=row[4],
        config=config_data,
        status=row[6],
        capture_status=row[7],
        created_at=row[8],
        updated_at=row[9]
    )
        
    conn.close()
    return teleop_group

@app.post("/api/teleop-groups", status_code=201)
async def create_teleop_group(group: TeleopGroupCreate):
    """新增遥操组"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 验证节点是否存在
        cursor.execute("SELECT id FROM nodes WHERE id = ?", (group.node_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=400, detail="Node not found")
            
        cursor.execute(
            """INSERT INTO teleop_groups (node_id, name, description, type, config) 
               VALUES (?, ?, ?, ?, ?)""",
            (group.node_id, group.name, group.description, group.type, 
             json.dumps(group.config))
        )
        id = cursor.lastrowid
        conn.commit()
        
        # 通知对应的Node更新配置
        await notify_node_config_update(group.node_id)
        
        return {"message": "遥操组已添加", "id": id}
        
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.put("/api/teleop-groups/{id}")
async def update_teleop_group(id: int, group: TeleopGroupUpdate):
    """更新遥操组"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 检查遥操组是否存在并获取node_id
        cursor.execute("SELECT id, node_id FROM teleop_groups WHERE id = ?", (id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Teleop group not found")
            
        node_id = row[1]
        
        # 如果没有提供status，则不更新status
        cursor.execute(
            """UPDATE teleop_groups SET name=?, description=?, type=?, config=?, updated_at=datetime('now') 
                WHERE id = ?""",
            (group.name, group.description, group.type, json.dumps(group.config), id)
        )
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Teleop group not found")
            
        conn.commit()
        
        # 通知对应的Node更新配置
        await notify_node_config_update(node_id)
        
        return {"message": "遥操组已更新"}
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/teleop-groups/{id}/start")
async def start_teleop_group(id: int):
    """启动遥操组"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 获取遥操组信息
    cursor.execute(
        """SELECT id, node_id, name, description, type, config, status 
           FROM teleop_groups WHERE id = ?""",
        (id,)
    )
    
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Teleop group not found")
        
    node_id = row[1]
    if node_id not in node_websockets:
        raise HTTPException(status_code=400, detail="Node not connected")
        
    try:
        # 发送启动遥操组的RPC请求
        websocket = node_websockets[node_id]
        rpc_id = int(time.time() * 1000)
        config_data = json.loads(row[5]) if isinstance(row[5], str) else row[5]
        # 确保config是列表类型
        if not isinstance(config_data, list):
            config_data = []
        
        rpc_request = {
            "jsonrpc": "2.0",
            "method": "node.start_teleop_group",
            "params": {
                "id": id,
                # "config": config_data
            },
            "id": rpc_id
        }
        
        # 发送请求
        await websocket.send_text(json.dumps(rpc_request))
        
        # 等待并处理响应
        result = await wait_for_response(websocket, node_id, rpc_id)
        
        # 检查结果，确保result是字典类型
        if not isinstance(result, dict) or result.get("success") is not True:
            raise HTTPException(status_code=400, detail="Failed to start teleop group")
            
        # 更新数据库中的状态
        cursor.execute(
            "UPDATE teleop_groups SET status = 1, updated_at = datetime('now') WHERE id = ?",
            (id,)
        )
        conn.commit()
        
        return {"message": "遥操组已启动"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/teleop-groups/{id}/stop")
async def stop_teleop_group(id: int):
    """停止遥操作组"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 获取遥操组信息
    cursor.execute(
        """SELECT id, node_id, name, description, type, config, status 
           FROM teleop_groups WHERE id = ?""",
        (id,)
    )
    
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Teleop group not found")
        
    node_id = row[1]
    if node_id not in node_websockets:
        raise HTTPException(status_code=400, detail="Node not connected")
        
    try:
        # 发送启动遥操组的RPC请求
        websocket = node_websockets[node_id]
        rpc_id = int(time.time() * 1000)
        
        rpc_request = {
            "jsonrpc": "2.0",
            "method": "node.stop_teleop_group",
            "params": {
                "id": id,
            },
            "id": rpc_id
        }
        
        # 发送请求
        await websocket.send_text(json.dumps(rpc_request))
        
        # 等待并处理响应
        result = await wait_for_response(websocket, node_id, rpc_id)
        
        # 检查结果，确保result是字典类型
        if not isinstance(result, dict) or result.get("success") is not True:
            raise HTTPException(status_code=400, detail="Failed to stop teleop group")
            
        # 更新数据库中的状态
        cursor.execute(
            "UPDATE teleop_groups SET status = 0, updated_at = datetime('now') WHERE id = ?",
            (id,)
        )
        conn.commit()
        
        return {"message": "遥操组已停止动"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.delete("/api/teleop-groups/{id}", status_code=204)
async def delete_teleop_group(id: int):
    """删除遥操作组"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 获取node_id用于通知
        cursor.execute("SELECT node_id FROM teleop_groups WHERE id = ?", (id,))
        row = cursor.fetchone()
        
        cursor.execute("DELETE FROM teleop_groups WHERE id = ?", (id,))
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Teleop group not found")
            
        conn.commit()
        
        if row:
            # 通知对应的Node更新配置
            await notify_node_config_update(row[0])
            
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/vrs", response_model=List[VRResponse])
async def get_vrs(uuid: Optional[str] = Query(None)):
    """获取VR头显列表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        if uuid:
            cursor.execute(
                "SELECT id, uuid, device_id, info, created_at, updated_at FROM vrs WHERE uuid = ?",
                (uuid,)
            )
        else:
            cursor.execute("SELECT id, uuid, device_id, info, created_at, updated_at FROM vrs")
        
        vrs = []
        for row in cursor.fetchall():
            try:
                info_data = json.loads(row[3]) if isinstance(row[3], str) else row[3]
            except:
                info_data = {}
                
            vrs.append(VRResponse(
                id=row[0],
                uuid=row[1],
                device_id=row[2],
                info=info_data,
                created_at=row[4],
                updated_at=row[5]
            ))
            
        return vrs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/vrs", status_code=201)
async def create_vr(vr: VRCreate):
    """创建VR头显记录"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO vrs (uuid, info) VALUES (?, ?)",
            (vr.uuid, json.dumps(vr.info) if vr.info else "{}")
        )
        vr_id = cursor.lastrowid
        conn.commit()
        
        return {"message": "头显已添加", "id": vr_id}
    except sqlite3.IntegrityError as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(status_code=409, detail="VR with this UUID already exists")
        else:
            raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.put("/api/vrs/{id}")
async def update_vr(id: int, vr: VRUpdate):
    """更新VR头显配置"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 检查VR是否存在
        cursor.execute("SELECT id FROM vrs WHERE id = ?", (id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="VR not found")
        
        # 构建更新语句
        update_fields = []
        params = []
        
        if vr.uuid is not None:
            update_fields.append("uuid = ?")
            params.append(vr.uuid)
            
        if vr.device_id is not None:
            update_fields.append("device_id = ?")
            params.append(vr.device_id)
            
        if vr.info is not None:
            update_fields.append("info = ?")
            params.append(json.dumps(vr.info))
            
        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")
            
        update_fields.append("updated_at = datetime('now')")
        params.append(id)
        
        query = f"UPDATE vrs SET {', '.join(update_fields)} WHERE id = ?"
        cursor.execute(query, params)
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="VR not found")
            
        conn.commit()
        
        return {"message": "配置已更新"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.delete("/api/vrs/{id}")
async def delete_vr(id: int):
    """删除VR头显记录"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 检查VR是否存在
        cursor.execute("SELECT id FROM vrs WHERE id = ?", (id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="VR not found")
        
        # 删除VR记录
        cursor.execute("DELETE FROM vrs WHERE id = ?", (id,))
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="VR not found")
            
        conn.commit()
        
        return {"message": "头显已删除"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# WebSocket端点
@app.websocket("/ws/rpc")
async def websocket_endpoint(websocket: WebSocket):
    """处理Node的WebSocket连接"""
    await websocket.accept()
    
    # 使用字典封装node_id，使其修改能传递到外层
    connection_context = {"node_id": None}
    try:
        # 继续处理后续消息
        while True:
            data = await websocket.receive_text()
            print(f"Received message: {data}")
            message = json.loads(data)
            
            # 处理JSON-RPC请求
            if "method" in message:
                response = await handle_jsonrpc_request(message, websocket, connection_context)
                if response:
                    await websocket.send_text(json.dumps(response))
            
            # 处理JSON-RPC响应
            elif "id" in message and ("result" in message or "error" in message):
                await handle_jsonrpc_response(message, connection_context["node_id"])
                
    except Exception as e:
        print(f"WebSocket连接错误: {e}")
    finally:
        # 清理连接的节点
        if connection_context["node_id"] and connection_context["node_id"] in node_websockets:
            del node_websockets[connection_context["node_id"]]
            print(f"Node {connection_context['node_id']} disconnected and removed from connection pool")

# 挂载静态文件夹
app.mount("/", StaticFiles(directory="static"), name="static")
@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/index.html")
# 启动时初始化数据库
@app.on_event("startup")
async def startup_event():
    init_tables(DB_PATH)
    from MQTTStatusSync import MQTTStatusSync
    sync_service = MQTTStatusSync(
        db_path="EasyTeleop.db",
        mqtt_broker="localhost",  # 修改为实际的MQTT服务器地址
        mqtt_port=1883
    )
    
    try:
        # 启动同步服务
        sync_service.start_sync()
        print("MQTT状态同步服务已启动")
            
    except Exception as e:
        print(f"MQTT状态同步服务运行出错: {str(e)}")
        sync_service.stop_sync()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
