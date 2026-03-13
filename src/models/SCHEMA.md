# Knowledge Graph Schema Contract

This document defines the schema for nodes and edges in the Brownfield Cartographer Knowledge Graph.

## Nodes

All nodes are defined using Pydantic models in `src/models/nodes.py`.

### 1. `ModuleNode`
- **Identity**: Relative file path.
- **Attributes**: `language`, `complexity_score`, `change_velocity_30d`, `is_dead_code_candidate`.
- **Children**: Contains `FunctionNode` and `ClassNode` lists.

### 2. `DatasetNode`
- **Identity**: Dataset name (table name, file name).
- **Attributes**: `storage_type`, `owner`, `is_source_of_truth`.

### 3. `TransformationNode`
- **Identity**: Unique transformation name.
- **Attributes**: `transformation_type`, `source_file`, `line_range`.

## Edges

Edges are typed using the `RelationshipType` Enum and `EdgeMetadata` model in `src/models/edges.py`.

### 1. `IMPORTS` (Module -> Module)
- Represents a static dependency between two source files.

### 2. `CONTAINS` (Module -> Function/Class)
- Represents the parent-child hierarchy within a module.

### 3. `READS` (Transformation -> Dataset)
- Represents a data ingress operation (e.g., SELECT from a table).

### 4. `WRITES` (Transformation -> Dataset)
- Represents a data egress operation (e.g., INSERT into a table).

### 5. `CALLS` (Function -> Function)
- Represents an execution dependency between two code components.

## Serialization Format

The graph is stored as a `MultiDiGraph` serialized to JSON:
```json
{
  "nodes": { "node_id": { "attr": "val" } },
  "edges": [
    { "source": "A", "target": "B", "key": "rel_type", "metadata": { ... } }
  ]
}
```
