"""协议配置 JSON 保存/加载。"""

import json
from pathlib import Path


class ConfigManager:
    def __init__(self, config_dir=None):
        if config_dir is None:
            config_dir = Path(__file__).parent / "protocol_configs"
        self._dir = Path(config_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, config: dict) -> Path:
        path = self._dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return path

    def load(self, name: str) -> dict:
        path = self._dir / f"{name}.json"
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_configs(self) -> list[str]:
        return sorted(
            p.stem for p in self._dir.glob("*.json")
        )
