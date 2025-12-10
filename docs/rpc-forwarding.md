# RPC 转发接口说明

## 目的
前端可以通过 HTTP 调用节点暴露的 JSON-RPC 方法，后端负责查询节点支持的 RPC 列表并转发调用。

## 新增 HTTP 接口（Backend）

### 获取节点 RPC 列表
- `GET /api/nodes/{id}/rpc`
- 响应示例
```json
{
    "methods": [
        {
            "name": "node.custom.realsense.find_device",
            "description": "扫描可用RealSense设备",
            "params": {}
        },
        {
            "name": "node.custom.test_device",
            "description": "测试设备连通性",
            "params": {
                "category": "string",
                "type": "string",
                "config": "object"
            }
        }
    ]
}
```

### 调用节点 RPC
- `POST /api/nodes/{id}/rpc`
- 请求体
```json
{
  "method": "node.test_device",
  "params": {
    "category": "robot",
    "type": "realman",
    "config": {"ip": "192.168.1.100"}
  }
}
```
- 响应体
```json
{ "result": { "success": true, "message": "Device connected successfully" } }
```

## Node 端新增 RPC
- `node.get_rpc_methods`：返回当前节点注册的 `node.*` 方法列表，供后端查询。

## 依赖与注意事项
- 节点需保持 WebSocket 连接（`/ws/rpc`）以接受转发的 RPC 调用。
- 调用失败会返回 HTTP 500，并包含节点返回的错误信息或连接状态错误。
