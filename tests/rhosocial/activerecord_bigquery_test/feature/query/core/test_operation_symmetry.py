# tests/rhosocial/activerecord_bigquery_test/feature/query/test_operation_symmetry.py
"""Same-family column and value classes must offer the same operations.

The P1 unification says a family is one thing on both sides: the class a
``Model.c.<field>`` builds (a column) and the class an operation result builds
(a value) attach the same operation groups, so a value that came out of an
expression can be used exactly like the column it came from. Drift between the
two sides is invisible until a caller hits it -- ``name.length()`` returning a
number that lost an operation the string column still has, say -- so the sets
are asserted equal here.

Definition of the compared set:

* public callables plus the operator dunders (``__add__`` ... ``__and__``);
* minus the names provided by :class:`NotANumberMixin`. The refusal set is a
  separate axis -- it answers "is this family a number", and whether a side
  declares the refusal or merely lacks the operator is pinned where it
  belongs (the family's own tests). Comparing the *offered* operations is
  what "same family, same groups" means.
"""

# tests/rhosocial/activerecord_bigquery_test/feature/query/test_operation_symmetry.py
import pytest

from rhosocial.activerecord.backend.expression import (
    ArrayColumn,
    BinaryColumn,
    BooleanColumn,
    TimestampColumn,
    IntegerColumn,
    JSONColumn,
    NumericColumn,
    StringColumn,
    UUIDColumn,
    XMLColumn,
)
from rhosocial.activerecord.backend.expression.declared import (
    ArrayAnnotation,
    BinaryAnnotation,
    BooleanAnnotation,
    IntegerAnnotation,
    JSONAnnotation,
    NumberAnnotation,
    TextAnnotation,
    TemporalAnnotation,
    UUIDAnnotation,
    XMLAnnotation,
)
from rhosocial.activerecord.backend.expression.mixins import NotANumberMixin

OPERATORS = {
    "__add__",
    "__sub__",
    "__mul__",
    "__truediv__",
    "__mod__",
    "__and__",
    "__or__",
    "__invert__",
    "__eq__",
    "__ne__",
    "__lt__",
    "__le__",
    "__gt__",
    "__ge__",
}

_REFUSALS = {name for name, value in vars(NotANumberMixin).items() if callable(value)}

#: Not operations on a value, so not part of what "the same operations" means.
#: ``collate`` and ``validate`` are a column's storage; ``get_params`` belongs to
#: the artifact rather than to the type; ``surface`` is the declaration of
#: which operations a node carries, which is the thing being compared here and so
#: cannot also be one of the things compared; and ``kind`` is a node's identity
#: on the wire (§4.9.2) -- defined once on the expression base, which an
#: annotation is not.
_NOT_OPERATIONS = {"collate", "validate", "get_params", "value_type_of", "kind"}


def _operations(cls):
    """The operation names *cls* offers: public callables + operator dunders."""
    names = set()
    for name in dir(cls):
        if name.startswith("_") and name not in OPERATORS:
            continue
        if callable(getattr(cls, name, None)):
            names.add(name)
    return names - _REFUSALS - _NOT_OPERATIONS


FAMILIES = [
    (StringColumn, TextAnnotation),
    (NumericColumn, NumberAnnotation),
    (IntegerColumn, IntegerAnnotation),
    (BooleanColumn, BooleanAnnotation),
    (TimestampColumn, TemporalAnnotation),
    (BinaryColumn, BinaryAnnotation),
    (UUIDColumn, UUIDAnnotation),
    (JSONColumn, JSONAnnotation),
    (ArrayColumn, ArrayAnnotation),
    (XMLColumn, XMLAnnotation),
]


@pytest.mark.parametrize("column_class, value_class", FAMILIES, ids=lambda c: c.__name__)
def test_the_two_sides_of_a_family_offer_the_same_operations(column_class, value_class):
    column_ops = _operations(column_class)
    value_ops = _operations(value_class)
    assert column_ops == value_ops, (
        f"{column_class.__name__} and {value_class.__name__} drifted apart:\n"
        f"  only on the column: {sorted(column_ops - value_ops)}\n"
        f"  only on the value:  {sorted(value_ops - column_ops)}"
    )
