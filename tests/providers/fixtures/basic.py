# tests/providers/fixtures/basic.py
"""BigQuery DDL for the ``feature/basic`` table group.

The layouts mirror the reference schemas used by the other backends
(``tests/rhosocial/activerecord_mysql_test/feature/basic/schema/*.sql`` in
python-activerecord-mysql, and the equivalent SQLite fixtures), adapted to
BigQuery Standard SQL and to the limitations of the goccy/bigquery-emulator:

* Emulated column types: ``INT64``, ``STRING``, ``BOOL``, ``FLOAT64``,
  ``NUMERIC``/``BIGNUMERIC``, ``DATETIME``, ``TIMESTAMP``, ``JSON``,
  ``ARRAY<...>``, ``BYTES``.
* No ``DEFAULT`` clause — the emulator rejects it in CREATE TABLE (and
  silently ignores ``ALTER COLUMN ... SET DEFAULT``), so column-level
  ``NOT NULL`` is relaxed to nullable for every non-primary-key column:
  insert statements that omit defaulted columns are legal in other backends
  only because of DDL defaults (e.g. mapped models inserting into ``users``).
  Model-level (Pydantic) defaults still provide the values the tests assert.
* No ``UNIQUE`` constraints, no secondary indexes, no foreign keys. None of
  these are enforced by BigQuery and the emulator rejects most of them.
* No ``AUTO_INCREMENT`` — the backend generates integer primary keys
  client-side (see ``BigQueryBackend.insert``).
* Table names are rendered dataset-qualified (``dataset.table``) because the
  anonymous emulator client has no default dataset configured.
"""

from typing import Callable, Dict


def _qualify(dataset: str, table_name: str) -> str:
    return f"`{dataset}`.`{table_name}`" if dataset else f"`{table_name}`"


def create_users_table(dataset: str, table_name: str = "users") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    username STRING,
    email STRING,
    age INT64,
    balance FLOAT64,
    is_active BOOL,
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_type_cases_table(dataset: str, table_name: str = "type_cases") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id STRING NOT NULL,
    username STRING,
    email STRING,
    tiny_int STRING,
    small_int STRING,
    big_int STRING,
    float_val STRING,
    double_val STRING,
    decimal_val STRING,
    char_val STRING,
    varchar_val STRING,
    text_val STRING,
    date_val STRING,
    time_val STRING,
    timestamp_val STRING,
    blob_val BYTES,
    json_val STRING,
    array_val STRING,
    is_active STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_type_tests_table(dataset: str, table_name: str = "type_tests") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id STRING NOT NULL,
    string_field STRING,
    int_field INT64,
    float_field FLOAT64,
    decimal_field FLOAT64,
    bool_field BOOL,
    datetime_field STRING,
    -- The emulator double-encodes values in JSON-typed columns (returns the
    -- JSON document base64-like wrapped as a JSON string literal), so the
    -- round-trip column is kept as plain STRING and JSON (de)serialization
    -- stays in the model's adapter layer.
    json_field STRING,
    nullable_field STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_validated_field_users_table(dataset: str, table_name: str = "validated_field_users") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    username STRING,
    email STRING,
    age INT64,
    balance NUMERIC(10, 2),
    credit_score INT64,
    status STRING,
    is_active BOOL,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_validated_users_table(dataset: str, table_name: str = "validated_users") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    username STRING,
    email STRING,
    age INT64,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_pydantic_validated_models_table(dataset: str, table_name: str = "pydantic_validated_models") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    code STRING,
    quantity INT64,
    step_count INT64,
    price NUMERIC(10, 2),
    start_at DATETIME,
    end_at DATETIME,
    status STRING,
    normalized_name STRING,
    created_token STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_bulk_users_table(dataset: str, table_name: str = "bulk_users") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    name STRING,
    age INT64,
    email STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_posts_table(dataset: str, table_name: str = "posts") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    author INT64,
    title STRING,
    content STRING,
    published_at DATETIME,
    published BOOL,
    created_at DATETIME,
    updated_at DATETIME,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_comments_table(dataset: str, table_name: str = "comments") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    post_ref INT64,
    author INT64,
    text STRING,
    created_at DATETIME,
    updated_at DATETIME,
    approved BOOL,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_column_mapping_items_table(dataset: str, table_name: str = "column_mapping_items") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    name STRING,
    item_total INT64,
    remarks INT64,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_mixed_annotation_items_table(dataset: str, table_name: str = "mixed_annotation_items") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    name STRING,
    tags STRING,
    meta STRING,
    description STRING,
    status STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_type_adapter_tests_table(dataset: str, table_name: str = "type_adapter_tests") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    name STRING,
    optional_name STRING,
    optional_age INT64,
    last_login STRING,
    is_premium BOOL,
    unsupported_union STRING,
    custom_bool STRING(3),
    optional_custom_bool STRING(3),
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_composite_pk_order_items_table(dataset: str, table_name: str = "order_items") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    order_id INT64 NOT NULL,
    product_id INT64 NOT NULL,
    quantity INT64,
    unit_price NUMERIC(10, 2),
    PRIMARY KEY (order_id, product_id) NOT ENFORCED
)"""


def create_store_inventory_table(dataset: str, table_name: str = "store_inventory") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    store_id INT64 NOT NULL,
    product_id INT64 NOT NULL,
    batch_id STRING(64) NOT NULL,
    stock INT64,
    PRIMARY KEY (store_id, product_id, batch_id) NOT ENFORCED
)"""


def create_orders_table(dataset: str, table_name: str = "orders") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    total NUMERIC(10, 2),
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_product_table(dataset: str, table_name: str = "product") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    name STRING,
    price FLOAT64,
    quantity INT64,
    PRIMARY KEY (id) NOT ENFORCED
)"""


TABLE_EXPRESSIONS: Dict[str, Callable] = {
    "users": create_users_table,
    "type_cases": create_type_cases_table,
    "type_tests": create_type_tests_table,
    "validated_field_users": create_validated_field_users_table,
    "validated_users": create_validated_users_table,
    "pydantic_validated_models": create_pydantic_validated_models_table,
    "bulk_users": create_bulk_users_table,
    "posts": create_posts_table,
    "comments": create_comments_table,
    "column_mapping_items": create_column_mapping_items_table,
    "mixed_annotation_items": create_mixed_annotation_items_table,
    "type_adapter_tests": create_type_adapter_tests_table,
    "order_items": create_composite_pk_order_items_table,
    "store_inventory": create_store_inventory_table,
    "orders": create_orders_table,
    "product": create_product_table,
}
