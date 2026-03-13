from pydantic import BaseModel, validator
from typing import List, Optional, Dict, Any
import os
from datetime import datetime


class FunctionNode(BaseModel):
    qualified_name: str
    parent_module: str
    signature: str
    purpose_statement: Optional[str] = None
    call_count_within_repo: int = 0
    is_public_api: bool = True


class ClassNode(BaseModel):
    name: str
    parent_module: str
    base_classes: List[str] = []
    methods: List[FunctionNode] = []
    purpose_statement: Optional[str] = None


class ModuleNode(BaseModel):
    path: str
    language: str
    purpose_statement: Optional[str] = None
    domain_cluster: Optional[str] = None
    complexity_score: float = 0.0
    change_velocity_30d: int = 0
    is_dead_code_candidate: bool = False
    last_modified: Optional[datetime] = None
    imports: List[str] = []
    functions: List[FunctionNode] = []
    classes: List[ClassNode] = []
    drift_report: Optional[Dict[str, Any]] = None

    @validator("path")
    def path_must_not_be_absolute(cls, v):
        if os.path.isabs(v):
            raise ValueError(f"Path must be relative to repo root: {v}")
        return v

    @validator("complexity_score")
    def score_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("Complexity score must be non-negative")
        return v


class DatasetNode(BaseModel):
    name: str
    storage_type: str  # [table|file|stream|api]
    schema_snapshot: Optional[Dict[str, Any]] = None
    freshness_sla: Optional[str] = None
    owner: Optional[str] = None
    is_source_of_truth: bool = False


class TransformationNode(BaseModel):
    name: str
    source_datasets: List[str]
    target_datasets: List[str]
    transformation_type: str
    source_file: str
    line_range: tuple[int, int]
    sql_query_if_applicable: Optional[str] = None
