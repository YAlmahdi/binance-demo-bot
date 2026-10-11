"""Immutable inert metadata. No file loaders, model objects or deployment pointers."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from .config import Recipe

def canonical_json(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)

def recipe_hash():
    return hashlib.sha256(canonical_json(asdict(Recipe())).encode()).hexdigest()

@dataclass(frozen=True)
class EngineeringArtifact:
    fixture_sha256: str
    sources_sha256: tuple[tuple[str,str], ...]
    recipe_sha256: str = field(default_factory=recipe_hash)
    version: str = field(default="v2-engineering-artifact-v001",init=False)
    evidence: str = field(default="SYNTHETIC_ONLY",init=False)
    state: str = field(default="INERT / NOT FITTED / NOT DEPLOYABLE",init=False)
    calendar: str = field(default="HYBRID_DESIGN_APPROVAL_REQUIRED; original 180-day prospective proposal preserved",init=False)
    risk: str = field(default="NOT CLEARED",init=False)

    def __post_init__(self):
        object.__setattr__(self,"sources_sha256",tuple(sorted(tuple(v) for v in self.sources_sha256)))
        if self.recipe_sha256!=recipe_hash() or re.fullmatch("[0-9a-f]{64}",self.fixture_sha256) is None:
            raise ValueError("Recipe/fixture SHA256 mismatch")
        names=set()
        for name,sha in self.sources_sha256:
            if (not name.startswith("src/") or any(p in ("",".","..") for p in name.split("/"))
                    or "\\" in name or ":" in name or not name.endswith(".py")
                    or re.fullmatch("[0-9a-f]{64}",sha) is None or name in names):
                raise ValueError("Safe unique source provenance required")
            names.add(name)

    def to_json(self):
        return canonical_json(asdict(self))

    @property
    def sha256(self):
        return hashlib.sha256(self.to_json().encode()).hexdigest()
