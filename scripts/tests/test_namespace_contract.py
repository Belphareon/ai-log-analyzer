from pathlib import Path

import pytest

from scripts.core.namespace_contract import (
    NamespaceContractError,
    namespace_contract_hash,
    resolve_namespace_contract,
)


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "namespaces.yaml"
    path.write_text(
        "namespaces:\n  - ns-a\n  - ns-b\n",
        encoding="utf-8",
    )
    return path


def test_namespace_contract_is_order_independent_and_hashed(tmp_path):
    contract = resolve_namespace_contract(
        "ns-b, ns-a",
        config_path=_config(tmp_path),
        strict=True,
    )

    assert contract.is_canonical
    assert contract.namespaces == contract.canonical_namespaces
    assert contract.contract_hash == namespace_contract_hash(contract.namespaces)


def test_namespace_contract_rejects_partial_override(tmp_path):
    with pytest.raises(NamespaceContractError, match="missing=.*ns-b"):
        resolve_namespace_contract(
            "ns-a",
            config_path=_config(tmp_path),
            strict=True,
        )


def test_namespace_contract_can_expose_partial_scope_for_replay(tmp_path):
    contract = resolve_namespace_contract(
        "ns-a",
        config_path=_config(tmp_path),
        strict=False,
    )

    assert contract.namespaces == ("ns-a",)
    assert not contract.is_canonical