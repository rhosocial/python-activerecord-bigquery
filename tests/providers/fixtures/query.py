# tests/providers/fixtures/query.py
"""BigQuery DDL for the ``feature/query`` table group.

The layouts mirror the reference schemas used by the other backends
(``python-activerecord-mysql/tests/rhosocial/activerecord_mysql_test/feature/
query/schema/*.sql``), adapted to BigQuery Standard SQL and to the limitations
of the goccy/bigquery-emulator: no ``DEFAULT`` clause (so non-PK columns are
left nullable; Pydantic-level model defaults supply the values), no
``UNIQUE``/indexes/foreign keys, and no ``AUTO_INCREMENT`` (the backend
generates integer primary keys client-side).

JSON columns of ``json_users`` are kept as plain ``STRING`` — the emulator
double-encodes values in JSON-typed columns, so (de)serialization stays in
the model's adapter layer.
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


def create_posts_table(dataset: str, table_name: str = "posts") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    user_id INT64,
    title STRING,
    content STRING,
    status STRING,
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_comments_table(dataset: str, table_name: str = "comments") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    user_id INT64,
    post_id INT64,
    content STRING,
    is_hidden BOOL,
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_orders_table(dataset: str, table_name: str = "orders") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    user_id INT64,
    order_number STRING,
    total_amount NUMERIC(10, 2),
    status STRING,
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_order_items_table(dataset: str, table_name: str = "order_items") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    order_id INT64,
    product_name STRING,
    quantity INT64,
    unit_price NUMERIC(10, 2),
    subtotal NUMERIC(10, 2),
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_json_users_table(dataset: str, table_name: str = "json_users") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    username STRING,
    email STRING,
    age INT64,
    created_at STRING,
    updated_at STRING,
    settings STRING,
    tags STRING,
    profile STRING,
    roles STRING,
    scores STRING,
    subscription STRING,
    preferences STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_nodes_table(dataset: str, table_name: str = "nodes") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    name STRING,
    parent_id INT64,
    value NUMERIC(10, 2),
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_extended_orders_table(dataset: str, table_name: str = "extended_orders") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    user_id INT64,
    order_number STRING,
    total_amount NUMERIC(10, 2),
    status STRING,
    priority STRING,
    region STRING,
    category STRING,
    product STRING,
    department STRING,
    year STRING,
    quarter STRING,
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_extended_order_items_table(dataset: str, table_name: str = "extended_order_items") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    order_id INT64,
    product_name STRING,
    quantity INT64,
    price NUMERIC(10, 2),
    category STRING,
    region STRING,
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_profiles_table(dataset: str, table_name: str = "profiles") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    user_id INT64,
    bio STRING,
    avatar_url STRING,
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_searchable_items_table(dataset: str, table_name: str = "searchable_items") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    name STRING,
    tags STRING,
    created_at STRING,
    updated_at STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


TABLE_EXPRESSIONS: Dict[str, Callable] = {
    "users": create_users_table,
    "posts": create_posts_table,
    "comments": create_comments_table,
    "orders": create_orders_table,
    "order_items": create_order_items_table,
    "json_users": create_json_users_table,
    "nodes": create_nodes_table,
    "extended_orders": create_extended_orders_table,
    "extended_order_items": create_extended_order_items_table,
    "profiles": create_profiles_table,
    "searchable_items": create_searchable_items_table,
}
