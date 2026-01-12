import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

CONFIG_FILE = Path("settings.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "power_level": 50,
    "max_load": 5.75, # Auto-calculated from Power Level (50%)
    "cool_down_target": 3.45,
    "export_path": "./exports",
    "target_network": "45.55.0.0/16",
    "scan_speed": 100
}

def load_config() -> Dict[str, Any]:
    """Load configuration from JSON, creating default if missing."""
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
            # Merge with defaults for new keys
            for k, v in DEFAULT_CONFIG.items():
                if k not in config:
                    config[k] = v
            return config
    except Exception:
        return DEFAULT_CONFIG

def save_config(config: Dict[str, Any]):
    """Persist configuration to JSON file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def get_setting(key: str) -> Optional[Any]:
    """Retrieve a single setting value."""
    return load_config().get(key, DEFAULT_CONFIG.get(key))
