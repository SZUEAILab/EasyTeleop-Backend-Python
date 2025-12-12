import json
import os
import sqlite3
from typing import Any, Dict, List

# Shared database path under a folder to allow volume mounting
DB_DIR = os.environ.get("DB_DIR", "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "EasyTeleop.db")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Return a sqlite3 connection using the shared DB path."""
    return sqlite3.connect(db_path)


def init_tables(db_path: str = DB_PATH) -> None:
    """Initialize tables if they do not exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid VARCHAR(36) UNIQUE NOT NULL,
            status BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS vrs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid VARCHAR(36) UNIQUE NOT NULL,
            device_id INTEGER,
            info TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (device_id) REFERENCES devices(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id INTEGER NOT NULL,
            name VARCHAR(20) NOT NULL,
            description TEXT,
            category VARCHAR(20) NOT NULL,
            type VARCHAR(20) NOT NULL,
            config TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status INTEGER DEFAULT 0,
            FOREIGN KEY (node_id) REFERENCES nodes (id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS teleop_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id INTEGER NOT NULL,
            name VARCHAR(20) NOT NULL,
            description TEXT,
            type VARCHAR(20) NOT NULL,
            config TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status BOOLEAN DEFAULT 0,
            capture_status BOOLEAN DEFAULT 0,
            FOREIGN KEY (node_id) REFERENCES nodes (id)
        )
        """
    )

    conn.commit()
    conn.close()


def get_node_devices(node_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return devices for a node with parsed config."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, name, description, category, type, config FROM devices WHERE node_id = ?",
        (node_id,),
    )

    devices: List[Dict[str, Any]] = []
    for row in cursor.fetchall():
        try:
            config_data = json.loads(row[5]) if isinstance(row[5], str) else row[5]
        except Exception:
            config_data = {}

        devices.append(
            {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "category": row[3],
                "type": row[4],
                "config": config_data,
            }
        )

    conn.close()
    return devices


def get_node_teleop_groups(node_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return teleop groups for a node with parsed config list."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, node_id, name, description, type, config FROM teleop_groups WHERE node_id = ?",
        (node_id,),
    )

    teleop_groups: List[Dict[str, Any]] = []
    for row in cursor.fetchall():
        try:
            config_data = json.loads(row[5]) if isinstance(row[5], str) else row[5]
            if not isinstance(config_data, list):
                config_data = []
        except Exception:
            config_data = []

        teleop_groups.append(
            {
                "id": row[0],
                "node_id": row[1],
                "name": row[2],
                "description": row[3],
                "type": row[4],
                "config": config_data,
            }
        )

    conn.close()
    return teleop_groups
