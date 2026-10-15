"""Indice del form_schema.json para buscar campos por ruta o etiqueta."""
from __future__ import annotations

from .form_schema import load_schema
from .textnorm import norm_loose


class Schema:
    def __init__(self, schema: dict | None = None):
        self.raw = schema or load_schema()
        self.root = self.raw["root"]
        self.fields = self.raw["fields"]
        self.by_path = {f["path"]: f for f in self.fields}
        self.order = {f["path"]: i for i, f in enumerate(self.fields)}
        self.repeats = {r["path"]: r for r in self.raw["repeats"]}
        self.matrices = {m["id"]: m for m in self.raw["matrices"]}

    def full(self, rel: str) -> str:
        rel = rel.strip()
        return rel if rel.startswith(self.root) else f"{self.root}/{rel.lstrip('/')}"

    def rel(self, path: str) -> str:
        return path.replace(self.root + "/", "")

    def get(self, rel_or_full: str) -> dict | None:
        return self.by_path.get(self.full(rel_or_full))

    def in_repeat(self, repeat_rel: str) -> list[dict]:
        rp = self.full(repeat_rel)
        return [f for f in self.fields if f["repeat"] == rp]

    def find_label(self, repeat_rel: str, label: str, startswith: bool = False) -> dict | None:
        want = norm_loose(label)
        for f in self.in_repeat(repeat_rel):
            if f["kind"] in ("note", "calculate"):
                continue
            got = norm_loose(f["label"])
            if got == want or (startswith and got.startswith(want)):
                return f
        return None

    def first_order(self, repeat_full: str) -> int:
        idx = [self.order[f["path"]] for f in self.fields if f["repeat"] == repeat_full]
        return min(idx) if idx else 10**6

    def option_labels(self, f: dict) -> list[str]:
        return [o["label"] for o in f.get("options", [])]
