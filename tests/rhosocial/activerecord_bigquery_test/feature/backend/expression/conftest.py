# tests/rhosocial/activerecord_bigquery_test/feature/backend/expression/conftest.py
"""The expression test area: construction -> render, no I/O, always parallel.

This directory holds this backend's expression-level tests. The org rules
(expression-dialect §12) give the area three properties, and the tests here are
written to all three:

* every case carries its own dialect instance and shares no mutable state;
* nothing opens a connection, creates a dataset, or touches the filesystem, so
  the whole area runs without the emulator;
* the cases are therefore independent, and parallelism is the default
  scheduling, not an option.

The parallel default itself cannot live in a conftest: pytest-xdist reads its
worker count before any conftest loads, so a conftest cannot inject ``-n``. The
default is wired one level out, in the repository-local plugin
``tests/plugins/expression_xdist.py`` (registered from ``pyproject.toml``),
which appends ``-n auto --dist=loadgroup`` when the invocation names only
pure-render targets and the caller has not chosen a worker count itself. The
plugin is the availability check too: with pytest-xdist absent it enables
nothing and says so.

This backend's pure-render tests are not all in this one directory. ``dialect/``
holds the same kind of test (formatting, literal spellings, kind identity), and
``../test_expression_roundtrip_all.py`` walks both core's expression package and
this backend's, so it lives above the subject tree. The plugin covers all three
and nothing else -- the backend modules that start a client, and the emulator
scenario loader, stay serial.

Serial cases: a test that genuinely cannot share a worker marks ``xdist_group``
explicitly and states the reason beside the mark. None does today -- no case
here has I/O to serialize around. ``--dist=loadscope`` and ``--dist=loadfile``
are refused by the plugin: they bind whole modules together and would hide
exactly the case-to-case dependencies parallelism exists to expose.
"""
