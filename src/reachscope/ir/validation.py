"""Fail closed when report-local identifiers cannot identify one object."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .serialize import IRDeserializeError


class _Identified(Protocol):
    @property
    def id(self) -> str: ...


class IRValidationError(IRDeserializeError):
    """An ambiguous report cannot safely bind judgments or evidence references."""


def validate_identifiers(components: Iterable[_Identified], chains: Iterable[_Identified]) -> None:
    """Preserve legacy ID values, rejecting duplicates within each namespace.

    The short legacy hashes are local labels, never signatures. A duplicate,
    including an exact repeated object, cannot safely use first/last-wins lookup.
    """
    for records in (components, chains):
        seen: set[str] = set()
        for record in records:
            identifier = record.id
            if identifier in seen:
                raise IRValidationError("Analysis contains duplicate local identifiers; evidence binding is ambiguous")
            seen.add(identifier)
