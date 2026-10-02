"""Canonical monitored-namespace contract shared by runtime entry points."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "namespaces.yaml"


class NamespaceContractError(ValueError):
    """Raised when runtime namespace coverage is not canonical."""


def normalize_namespaces(values: Any) -> Tuple[str, ...]:
    """Normalize a comma-separated or iterable namespace value."""
    if isinstance(values, str):
        values = values.split(",")
    if values is None:
        values = ()
    try:
        normalized = {
            str(value).strip()
            for value in values
            if str(value).strip()
        }
    except TypeError as error:
        raise NamespaceContractError("namespace value must be iterable") from error
    return tuple(sorted(normalized))


def namespace_contract_hash(namespaces: Iterable[str]) -> str:
    """Return the stable identity of a normalized namespace set."""
    payload = json.dumps(
        list(normalize_namespaces(namespaces)),
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_canonical_namespaces(config_path: Optional[Path | str] = None) -> Tuple[str, ...]:
    """Load and validate the repository namespace source of truth."""
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise NamespaceContractError(
            f"cannot load namespace contract from {path}: {error}"
        ) from error

    if not isinstance(document, dict) or not isinstance(document.get("namespaces"), list):
        raise NamespaceContractError(f"{path} must define a namespaces list")

    raw_values = document["namespaces"]
    if any(not isinstance(value, str) or not value.strip() for value in raw_values):
        raise NamespaceContractError(f"{path} contains an empty or non-string namespace")
    normalized = normalize_namespaces(raw_values)
    if len(normalized) != len(raw_values):
        raise NamespaceContractError(f"{path} contains duplicate namespaces")
    if not normalized:
        raise NamespaceContractError(f"{path} contains no namespaces")
    return normalized


def namespace_diff(expected: Iterable[str], actual: Iterable[str]) -> dict[str, list[str]]:
    expected_set = set(normalize_namespaces(expected))
    actual_set = set(normalize_namespaces(actual))
    return {
        "missing": sorted(expected_set - actual_set),
        "extra": sorted(actual_set - expected_set),
    }


def _strict_from_environment(default: bool = False) -> bool:
    raw = os.getenv("NAMESPACE_CONTRACT_STRICT")
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class NamespaceContract:
    """Resolved namespace scope and its reproducibility metadata."""

    namespaces: Tuple[str, ...]
    canonical_namespaces: Tuple[str, ...]
    source: str
    contract_hash: str

    @property
    def is_canonical(self) -> bool:
        return self.namespaces == self.canonical_namespaces

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespaces": list(self.namespaces),
            "canonical_namespaces": list(self.canonical_namespaces),
            "source": self.source,
            "contract_hash": self.contract_hash,
            "is_canonical": self.is_canonical,
        }


def resolve_namespace_contract(
    monitored_namespaces: Any = None,
    *,
    config_path: Optional[Path | str] = None,
    strict: Optional[bool] = None,
) -> NamespaceContract:
    """Resolve runtime scope and optionally reject partial configuration.

    An explicit argument wins over ``MONITORED_NAMESPACES``. With no override,
    the YAML contract is used. Strict mode compares sets, so ordering does not
    affect the contract hash or compatibility decision.
    """
    canonical = load_canonical_namespaces(config_path)
    explicit = monitored_namespaces is not None
    if explicit:
        namespaces = normalize_namespaces(monitored_namespaces)
        source = "argument"
    else:
        raw_environment = os.getenv("MONITORED_NAMESPACES", "").strip()
        if raw_environment:
            namespaces = normalize_namespaces(raw_environment)
            source = "environment"
        else:
            namespaces = canonical
            source = "yaml"

    if not namespaces:
        raise NamespaceContractError("resolved namespace contract is empty")

    strict_mode = _strict_from_environment(default=True) if strict is None else strict
    if strict_mode:
        diff = namespace_diff(canonical, namespaces)
        if diff["missing"] or diff["extra"]:
            raise NamespaceContractError(
                "monitored namespace contract mismatch: "
                f"missing={diff['missing'] or []}, extra={diff['extra'] or []}"
            )

    return NamespaceContract(
        namespaces=namespaces,
        canonical_namespaces=canonical,
        source=source,
        contract_hash=namespace_contract_hash(namespaces),
    )


def load_monitored_namespaces(*, strict: Optional[bool] = None) -> list[str]:
    """Compatibility loader used by fetch and threshold-training modules."""
    return list(resolve_namespace_contract(strict=strict).namespaces)