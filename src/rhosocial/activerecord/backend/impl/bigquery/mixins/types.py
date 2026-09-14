# src/rhosocial/activerecord/backend/impl/bigquery/mixins/types.py
"""BigQuery type support mixin."""
from __future__ import annotations

from typing import Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from rhosocial.activerecord.backend.expression.types import (
        TinyIntType,
        SmallIntType,
        IntegerType,
        BigIntType,
        RealType,
        FloatType,
        DoubleType,
        DecimalType,
        BooleanType,
        CharType,
        VarCharType,
        TextType,
        DateType,
        TimeType,
        TimeTzType,
        DateTimeType,
        TimestampType,
        TimestampTzType,
        BlobType,
        JsonType,
        JsonBType,
    )


class BigQueryTypeSupportMixin:
    """BigQuery data type support and formatting.

    Maps generic expression-layer types onto BigQuery Standard SQL column types.
    """

    def supports_data_type_tinyint(self) -> bool:
        return True

    def format_data_type_tinyint(self, data_type: TinyIntType) -> Tuple[str, tuple]:
        return "INT64", ()

    def supports_data_type_smallint(self) -> bool:
        return True

    def format_data_type_smallint(self, data_type: SmallIntType) -> Tuple[str, tuple]:
        return "INT64", ()

    def supports_data_type_integer(self) -> bool:
        return True

    def format_data_type_integer(self, data_type: IntegerType) -> Tuple[str, tuple]:
        return "INT64", ()

    def supports_data_type_bigint(self) -> bool:
        return True

    def format_data_type_bigint(self, data_type: BigIntType) -> Tuple[str, tuple]:
        return "INT64", ()

    def supports_data_type_real(self) -> bool:
        return True

    def format_data_type_real(self, data_type: RealType) -> Tuple[str, tuple]:
        return "FLOAT64", ()

    def supports_data_type_float(self) -> bool:
        return True

    def format_data_type_float(self, data_type: FloatType) -> Tuple[str, tuple]:
        return "FLOAT64", ()

    def supports_data_type_double(self) -> bool:
        return True

    def format_data_type_double(self, data_type: DoubleType) -> Tuple[str, tuple]:
        return "FLOAT64", ()

    def supports_data_type_decimal(self) -> bool:
        return True

    def format_data_type_decimal(self, data_type: DecimalType) -> Tuple[str, tuple]:
        if getattr(data_type, "precision", None) is not None:
            scale = getattr(data_type, "scale", 0) or 0
            return f"NUMERIC({data_type.precision}, {scale})", ()
        return "NUMERIC", ()

    def supports_data_type_boolean(self) -> bool:
        return True

    def format_data_type_boolean(self, data_type: BooleanType) -> Tuple[str, tuple]:
        return "BOOL", ()

    def supports_data_type_char(self) -> bool:
        return True

    def format_data_type_char(self, data_type: CharType) -> Tuple[str, tuple]:
        length = getattr(data_type, "length", None)
        return (f"STRING({length})", ()) if length else ("STRING", ())

    def supports_data_type_varchar(self) -> bool:
        return True

    def format_data_type_varchar(self, data_type: VarCharType) -> Tuple[str, tuple]:
        length = getattr(data_type, "length", None)
        return (f"STRING({length})", ()) if length else ("STRING", ())

    def supports_data_type_text(self) -> bool:
        return True

    def format_data_type_text(self, data_type: TextType) -> Tuple[str, tuple]:
        return "STRING", ()

    def supports_data_type_date(self) -> bool:
        return True

    def format_data_type_date(self, data_type: DateType) -> Tuple[str, tuple]:
        return "DATE", ()

    def supports_data_type_time(self) -> bool:
        return True

    def format_data_type_time(self, data_type: TimeType) -> Tuple[str, tuple]:
        return "TIME", ()

    def supports_data_type_timetz(self) -> bool:
        return True

    def format_data_type_timetz(self, data_type: TimeTzType) -> Tuple[str, tuple]:
        return "TIME", ()

    def supports_data_type_datetime(self) -> bool:
        return True

    def format_data_type_datetime(self, data_type: DateTimeType) -> Tuple[str, tuple]:
        return "DATETIME", ()

    def supports_data_type_timestamp(self) -> bool:
        return True

    def format_data_type_timestamp(self, data_type: TimestampType) -> Tuple[str, tuple]:
        return "TIMESTAMP", ()

    def supports_data_type_timestamptz(self) -> bool:
        return True

    def format_data_type_timestamptz(self, data_type: TimestampTzType) -> Tuple[str, tuple]:
        return "TIMESTAMP", ()

    def supports_data_type_blob(self) -> bool:
        return True

    def format_data_type_blob(self, data_type: BlobType) -> Tuple[str, tuple]:
        return "BYTES", ()

    def supports_data_type_json(self) -> bool:
        return True

    def format_data_type_json(self, data_type: JsonType) -> Tuple[str, tuple]:
        return "JSON", ()

    def supports_data_type_jsonb(self) -> bool:
        return True

    def format_data_type_jsonb(self, data_type: JsonBType) -> Tuple[str, tuple]:
        return "JSON", ()


__all__ = ['BigQueryTypeSupportMixin']
