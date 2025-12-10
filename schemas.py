from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class NodeRegisterRequest(BaseModel):
    uuid: str


class NodeRegisterResponse(BaseModel):
    id: int
    devices: List[Dict[str, Any]] = []
    teleop_groups: List[Dict[str, Any]] = []


class NodeResponse(BaseModel):
    id: int
    uuid: str
    status: bool
    created_at: str
    updated_at: str


class DeviceBase(BaseModel):
    name: str
    description: str
    category: str
    type: str
    config: Dict[str, Any]


class DeviceCreate(DeviceBase):
    node_id: int


class DeviceUpdate(DeviceBase):
    name: str
    description: str
    category: str
    type: str
    config: Dict[str, Any]


class DeviceInDB(DeviceBase):
    id: int
    node_id: int
    name: str
    description: str
    category: str
    type: str
    config: Dict[str, Any]
    status: int
    created_at: str
    updated_at: str


class DeviceResponse(BaseModel):
    id: int
    node_id: int
    name: str
    description: str
    category: str
    type: str
    config: Dict[str, Any]
    status: int
    created_at: str
    updated_at: str


class TeleopGroupBase(BaseModel):
    name: str
    description: str
    type: str
    config: List[int]


class TeleopGroupCreate(TeleopGroupBase):
    node_id: int


class TeleopGroupUpdate(TeleopGroupBase):
    pass


class TeleopGroupInDB(TeleopGroupBase):
    id: int
    node_id: int
    status: int
    capture_status: int
    created_at: str
    updated_at: str


class TeleopGroupResponse(BaseModel):
    id: int
    node_id: int
    name: str
    description: str
    type: str
    config: List[int]
    status: int
    capture_status: int
    created_at: str
    updated_at: str


class DeviceTestRequest(DeviceBase):
    """设备测试请求模型"""

    node_id: int = Field(..., description="节点ID")


class VRBase(BaseModel):
    uuid: str
    info: Optional[Dict[str, Any]] = None


class VRCreate(VRBase):
    pass


class VRUpdate(BaseModel):
    uuid: Optional[str] = None
    device_id: Optional[int] = None
    info: Optional[Dict[str, Any]] = None


class VRResponse(VRBase):
    id: int
    device_id: Optional[int] = None
    info: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str


class RPCCallResponse(BaseModel):
    result: Any


class NodeRPCCallRequest(BaseModel):
    method: str
    params: Optional[Dict[str, Any]] = None
