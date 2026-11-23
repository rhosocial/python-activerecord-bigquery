"""BigQuery backend type adapters."""
import datetime
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Type, Union

from rhosocial.activerecord.backend.adapters import (
    BitString,
    BitStringAdapterBase,
    Geometry,
    GeometryAdapterBase,
    GeometryCollection,
    IPAddress,
    IPAddressAdapterBase,
    LineString,
    MacAddress,
    MacAddressAdapterBase,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Multirange,
    Point,
    Polygon,
    Range,
    RangeAdapterBase,
    Vector,
    VectorAdapterBase,
)
from rhosocial.activerecord.backend.type_adapter import SQLTypeAdapter


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

    def from_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None,
                      **kwargs) -> Any:
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

    def from_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None,
                      **kwargs) -> Any:
        if value is None:
            return None
        return value


class BigQueryJSONAdapter(SQLTypeAdapter):
    """Adapts Python dict/list to BigQuery JSON and vice-versa.

    ``default`` / ``object_hook`` are forwarded to ``json.dumps`` / ``json.loads``
    so callers can plug in a neutral-type codec (see
    ``rhosocial.activerecord.backend.adapters.json_codec``). Both default to
    ``None``, which leaves serialization and decoding exactly as before.

    Note that ``object_hook`` only runs when the client hands back a JSON *text*
    value: values the driver has already decoded to ``dict``/``list`` are returned
    unchanged, because no ``json.loads`` call happens for them.
    """

    def __init__(
        self,
        default: Optional[Callable[[Any], Any]] = None,
        object_hook: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self._json_default = default
        self._json_object_hook = object_hook

    @property
    def supported_types(self) -> Dict[Type, List[Any]]:
        return {dict: [str], list: [str]}

    def to_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, default=self._json_default)
        return value

    def from_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None,
                      **kwargs) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            decoded = json.loads(value, object_hook=self._json_object_hook)
            # The goccy emulator stores a JSON string bound to a native ``JSON``
            # column as a JSON *string value* (it adds an extra layer of
            # quoting).  For a dict/list field a single ``json.loads`` then
            # still yields a string, so decode once more.  A correctly encoded
            # object decodes to a dict/list on the first pass and is returned
            # unchanged; the guard keeps scalar JSON strings from being
            # decoded a second time.
            if isinstance(decoded, str) and target_type in (dict, list):
                try:
                    decoded = json.loads(decoded, object_hook=self._json_object_hook)
                except (ValueError, TypeError):
                    pass
            return decoded
        return value


class BigQueryDecimalAdapter(SQLTypeAdapter):
    @property
    def supported_types(self) -> Dict[Type, List[Any]]:
        return {Decimal: [float, str, int, Decimal]}

    def to_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None) -> Any:
        if value is None:
            return None
        return value

    def from_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None,
                      **kwargs) -> Any:
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

    def from_database(self, value: Any, target_type: Type, options: Optional[Dict[str, Any]] = None,
                      **kwargs) -> Any:
        if value is None:
            return None
        return value


# --- Neutral-type adapters -------------------------------------------------
#
# ``rhosocial.activerecord.backend.adapters`` defines driver-independent types;
# this backend pins one wire form per type. The table is authoritative:
#
#   neutral type   column                     wire value
#   Geometry       GEOGRAPHY                  WKT text (``POINT (1 2)``)
#   Vector         ARRAY<FLOAT64> / STRING    Python ``list`` of floats, or
#                                             JSON text ``[1.0, 2.5]``
#   BitString      BYTES / STRING             whole bytes (bit_length % 8 == 0),
#                                             or canonical ``"0"``/``"1"`` text
#   Range          RANGE<DATE|DATETIME|TIMESTAMP>
#                                             ``{"start": ..., "end": ...}``
#                                             (the google-cloud-bigquery row
#                                             representation), or the literal
#                                             ``[start, end)`` string
#   Multirange     STRING (no native type)    JSON text of Range objects
#   MacAddress     STRING                     canonical lowercase colon text
#   IPAddress      STRING (no native type)    canonical IPv4/IPv6 text
#
# BigQuery RANGE is always half-open ``[start, end)`` and uses NULL endpoints
# for ``UNBOUNDED``. The Python client (google-cloud-bigquery 3.47) has no
# ``Range`` class: query results come back as ``{"start": ..., "end": ...}``
# (see ``google.cloud.bigquery._helpers.CellDataParser.range_to_py``), and
# load-job rows are serialized from the same mapping shape. The adapter
# therefore round-trips that dict directly, and only accepts neutral bounds
# that the column can actually represent.
#
# The client's RANGE element support is limited to DATE, DATETIME and
# TIMESTAMP; those are also the only element types BigQuery accepts in
# ``RANGE<...>`` declarations.
_GEOMETRY_TYPES = (
    Geometry,
    Point,
    LineString,
    Polygon,
    MultiPoint,
    MultiLineString,
    MultiPolygon,
    GeometryCollection,
)


class BigQueryGeometryAdapter(GeometryAdapterBase):
    """Encodes neutral geometries as WKT in a ``GEOGRAPHY`` column.

    BigQuery returns ``GEOGRAPHY`` values as WKT text, and accepts a WKT string
    parameter/literal for a ``GEOGRAPHY`` column, so the wire form is WKT on
    both sides. (GeoJSON remains available through BigQuery's ``ST_AsGeoJSON``
    function, but it is not the client's native read representation.)
    """

    def __init__(self):
        super().__init__()
        for geometry_type in _GEOMETRY_TYPES:
            self.register_type(geometry_type, str)

    def _encode(self, geometry: Geometry, target_type: Type, options: Dict[str, Any]) -> str:
        return geometry.to_wkt()

    def _decode(self, value: Any, options: Dict[str, Any]) -> Geometry:
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        return Geometry.from_wkt(self._require_text(value))


class BigQueryVectorAdapter(VectorAdapterBase):
    """Encodes neutral vectors for a BigQuery column.

    Two wire forms, decided by the target type:

    * ``list`` — a native ``ARRAY<FLOAT64>`` binding, which the client binds as
      a Python list and returns as a list;
    * ``str`` — the canonical JSON list, ``[1.0, 2.5]``, for a ``STRING`` column
      (the shared text carrier).  This is also what the emulator returns for a
      ``STRING`` column, so it is decoded both ways.
    """

    def __init__(self):
        super().__init__()
        self.register_type(Vector, list)
        self.register_type(Vector, str)

    def _encode(self, vector: Vector, target_type: Type, options: Dict[str, Any]) -> Any:
        if target_type is str:
            return json.dumps(vector.to_json_value(), ensure_ascii=False)
        return [float(item) for item in vector.values]

    def _decode(self, value: Any, options: Dict[str, Any]) -> Vector:
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            return Vector.from_json_value(json.loads(value))
        if isinstance(value, (list, tuple)):
            return Vector.from_json_value(list(value))
        raise ValueError(f"expected a list or JSON text from a vector column, got {type(value).__name__}")


class BigQueryBitStringAdapter(BitStringAdapterBase):
    """Encodes neutral bit strings for a BigQuery column.

    Two wire forms, decided by the target type:

    * ``bytes`` — a ``BYTES`` column, which carries only whole bytes, so a bit
      length that is not a multiple of 8 cannot be represented losslessly.
      Such a value is rejected instead of silently padding or truncating;
    * ``str`` — the canonical ``"0"``/``"1"`` text of the significant bits, for a
      ``STRING`` column, which keeps the bit length exactly (leading zeros
      included) and is what the shared text carrier declares.
    """

    def __init__(self):
        super().__init__()
        self.register_type(BitString, bytes)
        self.register_type(BitString, str)

    def _encode(self, bits: BitString, target_type: Type, options: Dict[str, Any]) -> Any:
        if target_type is str:
            return bits.to_bits()
        if bits.bit_length % 8:
            raise ValueError(
                f"BigQuery BYTES carries whole bytes, but bit_length is {bits.bit_length}; "
                "use a STRING column if the sub-byte length must be preserved"
            )
        return bits.data

    def _decode(self, value: Any, options: Dict[str, Any]) -> BitString:
        if isinstance(value, str):
            return BitString.from_bits(value)
        return BitString.from_bytes(self._require_bytes(value))


class BigQueryRangeAdapter(RangeAdapterBase):
    """Encodes neutral ranges for BigQuery ``RANGE<...>`` columns.

    Wire form: a ``{"start": ..., "end": ...}`` mapping (the representation
    produced by the google-cloud-bigquery row parser and accepted by the insert
    serializer), or a ``[start, end)`` literal string. ``None`` endpoints mean
    ``UNBOUNDED``. BigQuery ranges are always half-open, so only neutral
    bounds that map onto ``[start, end)`` are accepted.

    ``Multirange`` has no BigQuery type; it is stored as JSON text in a
    ``STRING`` column instead (target ``str``).

    Execution-layer caveat: this backend binds DML values as positional query
    parameters (``BigQueryBackend._build_job_config``), which turns a ``dict``
    into a STRUCT parameter. A write to an actual ``RANGE`` column therefore
    needs a ``google.cloud.bigquery.RangeQueryParameter`` at the execution
    layer; the mapping produced here is the client's row / load-job
    representation (and the literal form can be inlined into SQL text), but it
    is not reachable through the current parameter binder. Reading a RANGE
    column is unaffected: the client's row parser returns the same mapping
    this adapter decodes.
    """

    def __init__(self):
        super().__init__()
        self.register_type(Range, dict)
        self.register_type(Range, str)
        self.register_type(Multirange, str)

    def _encode(
        self, value: Union[Range, Multirange], target_type: Type, options: Dict[str, Any]
    ) -> Any:
        if isinstance(value, Multirange):
            if target_type is not str:
                raise ValueError(
                    "BigQuery has no MULTIRANGE type; store neutral Multirange values "
                    "as JSON text in a STRING column (target str)"
                )
            return json.dumps(value.to_json_value(), ensure_ascii=False)

        if value.empty:
            raise ValueError("BigQuery RANGE cannot represent an empty range")
        self._require_half_open(value)

        if target_type is str:
            return "[{}, {})".format(
                _bq_literal_endpoint(value.lower),
                _bq_literal_endpoint(value.upper),
            )
        if target_type is dict:
            return {"start": value.lower, "end": value.upper}
        raise ValueError(
            "BigQuery RANGE is written either as a {'start','end'} dict or as a "
            f"[start, end) literal string, not {getattr(target_type, '__name__', target_type)!r}"
        )

    def _decode(
        self, value: Any, target_type: Type, options: Dict[str, Any]
    ) -> Union[Range, Multirange]:
        if isinstance(value, dict):
            if target_type is Multirange:
                raise ValueError("expected JSON text for a Multirange, got a RANGE mapping")
            if "start" not in value or "end" not in value:
                raise ValueError("RANGE mapping must contain 'start' and 'end'")
            return Range(value["start"], value["end"], "[)")

        text = self._require_text(value).strip()
        if text.startswith("[") and text.endswith(")"):
            if target_type is Multirange:
                raise ValueError("expected a JSON array of ranges, got a RANGE literal")
            return self._decode_literal(text)
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError(
                "Multirange JSON text must decode to an array, "
                f"got {type(payload).__name__}"
            )
        if target_type is Range:
            raise ValueError("expected a RANGE value, got a Multirange JSON array")
        return Multirange.from_json_value(payload)

    @staticmethod
    def _require_half_open(value: Range) -> None:
        if value.lower is not None and value.bounds[0] != "[":
            raise ValueError(
                f"BigQuery RANGE has an inclusive lower bound, so neutral bounds "
                f"{value.bounds!r} cannot be represented"
            )
        if value.upper is not None and value.bounds[1] != ")":
            raise ValueError(
                f"BigQuery RANGE has an exclusive upper bound, so neutral bounds "
                f"{value.bounds!r} cannot be represented"
            )

    def _decode_literal(self, text: str) -> Range:
        if not (text.startswith("[") and text.endswith(")")):
            raise ValueError(f"RANGE literal must look like [start, end), got {text!r}")
        start_text, end_text = text[1:-1].split(",", 1)
        return Range(
            _bq_parse_endpoint(start_text),
            _bq_parse_endpoint(end_text),
            "[)",
        )


def _bq_literal_endpoint(value: Any) -> str:
    """Render one BigQuery RANGE literal endpoint (``UNBOUNDED`` for ``None``)."""
    if value is None:
        return "UNBOUNDED"
    if isinstance(value, datetime.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def _bq_parse_endpoint(text: str) -> Any:
    """Parse one endpoint of a ``[start, end)`` literal."""
    text = text.strip()
    if text == "UNBOUNDED":
        return None
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1].replace("''", "'")
    # The neutral contract carries integer (and, on some backends, decimal)
    # range elements through a text carrier, so the literal text is the neutral
    # element's own spelling.  Parse the numeric spellings before the date ones:
    # ``int("2024-01-01")`` fails, but a bare ``"1"`` is a number, not a string.
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        pass
    try:
        if "T" in text or " " in text:
            return datetime.datetime.fromisoformat(text)
        return datetime.date.fromisoformat(text)
    except ValueError:
        return text


class BigQueryMacAddressAdapter(MacAddressAdapterBase):
    """Encodes neutral MAC addresses as canonical text in a ``STRING`` column.

    BigQuery has no MAC type; the wire value is the lowercase colon-separated
    form produced by ``str(MacAddress)``.
    """

    def __init__(self):
        super().__init__()
        self.register_type(MacAddress, str)

    def _encode(self, mac: MacAddress, target_type: Type, options: Dict[str, Any]) -> str:
        return str(mac)

    def _decode(self, value: Any, options: Dict[str, Any]) -> MacAddress:
        return MacAddress.parse(self._require_text(value))


class BigQueryIPAddressAdapter(IPAddressAdapterBase):
    """Encodes neutral IP addresses as canonical text in a ``STRING`` column.

    BigQuery has no IP type; the wire value is the canonical compressed form
    produced by ``str(IPAddress)`` (``192.0.2.1`` / ``2001:db8::1``).
    """

    def __init__(self):
        super().__init__()
        self.register_type(IPAddress, str)

    def _encode(self, ip_addr: IPAddress, target_type: Type, options: Dict[str, Any]) -> str:
        return str(ip_addr)

    def _decode(self, value: Any, options: Dict[str, Any]) -> IPAddress:
        return IPAddress.parse(self._require_text(value))
