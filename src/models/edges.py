from enum import Enum
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any


class RelationshipType(str, Enum):
    IMPORTS = "imports"  # Module -> Module
    CONTAINS = "contains"  # Module -> Function/Class
    READS = "reads"  # Transformation -> Dataset
    WRITES = "writes"  # Transformation -> Dataset
    CALLS = "calls"  # Function -> Function


class EdgeMetadata(BaseModel):
    rel_type: RelationshipType
    weight: float = 1.0
    properties: Dict[str, Any] = Field(default_factory=dict)
    source_line: Optional[int] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @validator("weight")
    def weight_must_be_positive(cls, v):
        if v < 0:
            raise ValueError("Weight must be non-negative")
        return v
