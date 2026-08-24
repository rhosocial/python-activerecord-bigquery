"""BigQuery backend type adapters."""
import json
from decimal import Decimal
from typing import Any, Dict, List, Optional, Type, Union

from rhosocial.activerecord.backend.type_adapter import SQLTypeAdapter
from .types import BigQueryStruct, BigQueryArray, BigQueryJSON


class BigQueryStructAdapter(SQLTypeAdapter):
    @property
    def supported_types(self) -> Dict[Type, List[Any]]:
        return {dict: [dict]}

    def to_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        return value

    def to_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        return value

    def from_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        return value


class BigQueryArrayAdapter(SQLTypeAdapter):
    @property
    def supported_types(self) -> Dict[Type, List[Any]]:
        return {list: [list]}

    def to_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        if isinstance(value, list):
            return value
        return value

    def from_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        return value


class BigQueryJSONAdapter(SQLTypeAdapter):
    @property
    def supported_types(self) -> Dict[Type, List[Any]]:
        return {dict: [str], list: [str]}

    def to_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return value

    def from_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        return value


class BigQueryDecimalAdapter(SQLTypeAdapter):
    @property
    def supported_types(self) -> Dict[Type, List[Any]]:
        return {Decimal: [float, str, int, Decimal]}

    def to_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        return value

    def from_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class BigQueryTimestampAdapter(SQLTypeAdapter):
    @property
    def supported_types(self) -> Dict[Type, List[Any]]:
        import datetime
        return {datetime.datetime: [str]}

    def to_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        return value

    def from_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        return value
