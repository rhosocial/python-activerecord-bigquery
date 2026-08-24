# tests/providers/fixtures/relation.py
"""BigQuery DDL for the ``feature/relation`` table group.

The layouts mirror the reference schemas used by the other backends
(``python-activerecord-mysql/tests/providers/relation.py``), adapted to
BigQuery Standard SQL and to the limitations of the goccy/bigquery-emulator:
no ``DEFAULT`` clause, no ``UNIQUE``/indexes/foreign keys, no
``AUTO_INCREMENT`` (primary keys are generated client-side by the backend).
JSON payload columns (``settings``, ``metadata``, ``meta``) are kept as plain
``STRING`` — the relation fixture models declare them as ``str`` and the
emulator double-encodes real JSON columns.
"""

from typing import Callable, Dict


def _qualify(dataset: str, table_name: str) -> str:
    return f"`{dataset}`.`{table_name}`" if dataset else f"`{table_name}`"


def create_employees_table(dataset: str, table_name: str = "employees") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    username STRING,
    department_id INT64,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_departments_table(dataset: str, table_name: str = "departments") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    name STRING,
    description STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_authors_table(dataset: str, table_name: str = "authors") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    name STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_books_table(dataset: str, table_name: str = "books") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    title STRING,
    author_id INT64,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_chapters_table(dataset: str, table_name: str = "chapters") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    title STRING,
    book_id INT64,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_profiles_table(dataset: str, table_name: str = "profiles") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    bio STRING,
    author_id INT64,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_users_table(dataset: str, table_name: str = "users") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    name STRING,
    email STRING,
    settings STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_posts_table(dataset: str, table_name: str = "posts") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    title STRING,
    body STRING,
    user_id INT64,
    view_count INT64,
    metadata STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_comments_table(dataset: str, table_name: str = "comments") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    body STRING,
    post_id INT64,
    meta STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_relation_boundary_owners_table(dataset: str, table_name: str = "relation_boundary_owners") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    name STRING,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_relation_boundary_profiles_table(dataset: str, table_name: str = "relation_boundary_profiles") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    bio STRING,
    owner_id INT64,
    PRIMARY KEY (id) NOT ENFORCED
)"""


def create_relation_boundary_posts_table(dataset: str, table_name: str = "relation_boundary_posts") -> str:
    return f"""
CREATE TABLE {_qualify(dataset, table_name)} (
    id INT64 NOT NULL,
    title STRING,
    owner_id INT64,
    PRIMARY KEY (id) NOT ENFORCED
)"""


TABLE_EXPRESSIONS: Dict[str, Callable] = {
    "employees": create_employees_table,
    "departments": create_departments_table,
    "authors": create_authors_table,
    "books": create_books_table,
    "chapters": create_chapters_table,
    "profiles": create_profiles_table,
    "users": create_users_table,
    "posts": create_posts_table,
    "comments": create_comments_table,
    "relation_boundary_owners": create_relation_boundary_owners_table,
    "relation_boundary_profiles": create_relation_boundary_profiles_table,
    "relation_boundary_posts": create_relation_boundary_posts_table,
}
