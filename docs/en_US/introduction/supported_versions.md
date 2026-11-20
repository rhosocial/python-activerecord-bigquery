# Supported versions

## Python

Python **3.10 through 3.14** on the standard (GIL) builds.

## Client and service

* Driver: `google-cloud-bigquery` (the REST client). Both the synchronous and the
  asynchronous backend use the client's own async support; there is no thread-pool shim.
* SQL dialect: GoogleSQL (BigQuery Standard SQL). Legacy SQL is not the target of the
  renderer.
* The dialect's feature level is `3.0.0` by default. BigQuery does not expose a server
  release over SQL, so this number is a *feature level*, not a negotiated server version;
  introspection records it as such rather than presenting it as a server version.

## Core library

The backend is built against the matching development line of `rhosocial-activerecord`.
Install the two together rather than pulling a released backend on its own — a mismatch
between the core expression layer and this dialect is the most likely source of missing
nodes or probes. See the dependency note on the [documentation home](../README.md).

## Emulator

CI and local integration tests run against `goccy/bigquery-emulator`, not a real GCP
account. The emulator implements a subset of GoogleSQL and has its own `COLUMNS` coverage;
differences are handled in favour of the real service. See
[Testing with the BigQuery emulator](../testing/README.md) and the
[`COLUMNS` projection and the emulator](../introspection/README.md#the-columns-projection-and-the-emulator)
section of the introspection guide.
