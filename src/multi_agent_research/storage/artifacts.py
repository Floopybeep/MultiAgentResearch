"""Content-addressed artifacts. Never overwrite an existing payload."""

import hashlib
import json
from pathlib import Path


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def put(self, value) -> str:
        data = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
        key = hashlib.sha256(data).hexdigest()
        path = self.root / f"{key}.json"
        try:
            with path.open("xb") as file:
                file.write(data)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError("Artifact hash collision or corruption")
        return key

    def get(self, key: str):
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Invalid artifact reference")
        data = (self.root / f"{key}.json").read_bytes()
        if hashlib.sha256(data).hexdigest() != key:
            raise ValueError("Corrupted artifact")
        return json.loads(data)
