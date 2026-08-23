"""BigQuery-specific types."""
from typing import Any, Dict, List


class BigQueryStruct:
    def __init__(self, fields: Dict[str, Any]):
        self.fields = fields


class BigQueryArray:
    def __init__(self, values: List[Any]):
        self.values = values


class BigQueryJSON:
    def __init__(self, data: Dict[str, Any]):
        self.data = data
