# src/rhosocial/activerecord/backend/impl/bigquery/cli/connection.py
"""Connection argument parsing and backend creation for the BigQuery CLI.

Every flag defaults to the environment variable of the same name, and each
one maps one-to-one onto a :class:`BigQueryConnectionConfig` field: that is
what "the same variables the config uses" means here, since the config
itself reads no environment -- a caller (this CLI, the example script)
supplies what it read.

The two Google variables are read as fallbacks because
``google-cloud-bigquery`` honours them natively: ``GOOGLE_APPLICATION_CREDENTIALS``
is where Application Default Credentials look for a service-account key,
and ``GOOGLE_CLOUD_PROJECT`` is the project it falls back to when the client
is built without one.

No flag and no variable is required: an example run with nothing set is how
a caller learns which variable they still have to set.
"""

import os

#: Environment variable names, one per connection argument. Kept beside the
#: arguments so the two cannot drift apart.
ENV_PROJECT = "BIGQUERY_PROJECT"
ENV_PROJECT_FALLBACK = "GOOGLE_CLOUD_PROJECT"
ENV_DATASET = "BIGQUERY_DATASET"
ENV_LOCATION = "BIGQUERY_LOCATION"
ENV_CREDENTIALS_PATH = "BIGQUERY_CREDENTIALS_PATH"
ENV_CREDENTIALS_PATH_FALLBACK = "GOOGLE_APPLICATION_CREDENTIALS"
ENV_CREDENTIALS_JSON = "BIGQUERY_CREDENTIALS_JSON"
ENV_API_ENDPOINT = "BIGQUERY_API_ENDPOINT"


def add_connection_args(parser):
    """Add the BigQuery connection arguments to a subcommand parser.

    Args:
        parser: The ``argparse`` parser the arguments are added to.
    """
    parser.add_argument(
        "--project",
        default=os.getenv(ENV_PROJECT) or os.getenv(ENV_PROJECT_FALLBACK),
        help=("Google Cloud project ID (env: BIGQUERY_PROJECT, or " "GOOGLE_CLOUD_PROJECT)"),
    )
    parser.add_argument(
        "--dataset",
        default=os.getenv(ENV_DATASET),
        help=(
            "Default dataset ID (env: BIGQUERY_DATASET). The dataset is "
            "BigQuery's schema level, so it is what the schema argument "
            "defaults to."
        ),
    )
    parser.add_argument(
        "--location",
        default=os.getenv(ENV_LOCATION),
        help="Dataset location, e.g. US or eu (env: BIGQUERY_LOCATION)",
    )
    parser.add_argument(
        "--credentials-path",
        default=(os.getenv(ENV_CREDENTIALS_PATH) or os.getenv(ENV_CREDENTIALS_PATH_FALLBACK)),
        help=(
            "Path to a service-account JSON key file (env: "
            "BIGQUERY_CREDENTIALS_PATH, or GOOGLE_APPLICATION_CREDENTIALS)"
        ),
    )
    parser.add_argument(
        "--credentials-json",
        default=os.getenv(ENV_CREDENTIALS_JSON),
        help=(
            "Service-account key as a JSON string (env: "
            "BIGQUERY_CREDENTIALS_JSON). Ignored when --credentials-path "
            "is given."
        ),
    )
    parser.add_argument(
        "--api-endpoint",
        default=os.getenv(ENV_API_ENDPOINT),
        help=(
            "BigQuery API endpoint override, e.g. http://localhost:9050 "
            "for the emulator (env: BIGQUERY_API_ENDPOINT)"
        ),
    )
    parser.add_argument(
        "--use-async",
        action="store_true",
        help="Use the asynchronous backend and introspector",
    )


def resolve_connection_config_from_args(args):
    """Build a :class:`BigQueryConnectionConfig` from parsed args.

    Args:
        args: The parsed namespace :func:`add_connection_args` filled.

    Returns:
        The connection config the backend is built from.
    """
    import json

    from rhosocial.activerecord.backend.impl.bigquery.config import (
        BigQueryConnectionConfig,
    )

    credentials_json = None
    if args.credentials_json:
        try:
            credentials_json = json.loads(args.credentials_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Error: --credentials-json is not valid JSON: {exc}") from exc

    return BigQueryConnectionConfig(
        project=args.project,
        dataset=args.dataset,
        location=args.location,
        credentials_path=args.credentials_path,
        credentials_json=credentials_json,
        api_endpoint=args.api_endpoint,
    )
