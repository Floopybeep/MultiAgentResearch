import hashlib
from importlib.resources import files


def load(role):
    return files(__package__).joinpath(f"{role}.md").read_text()


def hashes():
    return {r: hashlib.sha256(load(r).encode()).hexdigest() for r in ("lead", "worker", "citation")}
