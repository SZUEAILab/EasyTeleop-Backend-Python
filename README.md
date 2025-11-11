# EasyTeleop Backend Python

EasyTeleop Python后端是EasyTeleop系统的节点控制系统，负责设备控制和状态管理。它与Go后端服务协同工作，通过WebSocket进行JSON-RPC通信。

## 功能特性

- 设备控制和状态管理
- WebSocket通信支持
- MQTT状态同步
- RESTful API接口
- SQLite数据库存储

## 目录结构

```
EasyTeleop-Backend-Python/
├── backend.py              # 主服务程序
├── MQTTStatusSync.py       # MQTT状态同步模块
├── run_mqtt_sync.py        # MQTT同步服务运行脚本
├── EasyTeleop.db           # SQLite数据库文件
├── static/                 # 静态资源目录
├── docs/                   # 文档目录
└── README.md               # 项目说明文件
```

## 安装依赖

```bash
pip install -r requirements.txt
```

或者使用pipenv:

```bash
pipenv install
```

## 运行服务

### 启动主服务

```bash
python backend.py
```

### 启动MQTT状态同步服务

```bash
python run_mqtt_sync.py
```

## 配置

系统使用SQLite数据库，默认数据库文件为`EasyTeleop.db`。如需修改MQTT服务器配置，请编辑`run_mqtt_sync.py`文件。

## API文档

详细API文档请参见[docs/api.md](docs/api.md)。

## 数据库说明

数据库结构说明请参见[docs/database.md](docs/database.md)。