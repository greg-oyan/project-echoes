"""Bounded object-store and package tests; no cloud calls are made."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from echoes.final_discovery.inputs import (
    InputAuthenticationError,
    InputExpectation,
    LocalObjectStore,
    ObjectInventoryEntry,
    ObjectStore,
    ObjectStoreConflictError,
    ObjectStoreError,
    ObjectStoreIdentity,
    RcloneB2ObjectStore,
    create_deterministic_package,
    inventory_directory,
    materialize_authenticated_input,
    resume_or_upload_and_verify_tree,
    upload_and_verify_tree,
    verify_materialized_input,
    verify_package,
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_canonical_tree(root: Path) -> tuple[InputExpectation, dict[str, bytes]]:
    root.mkdir(parents=True)
    files = {
        "lexical_metadata/part-00000.parquet": b"metadata fixture\n",
        "indexes/lemma/matrix.npz": b"sparse fixture\x00\x01",
    }
    for relative, value in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    manifest = {
        "schema_version": 1,
        "table_counts": {"lexical_metadata": 1},
        "table_logical_sha256": {"lexical_metadata": "1" * 64},
        "table_physical_sha256": {"lexical_metadata": "2" * 64},
        "artifacts": {"lexical_metadata": {}},
        "file_sha256": {relative: _sha256(value) for relative, value in files.items()},
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    (root / "table-hashes.json").write_bytes(manifest_bytes)
    identity = ObjectStoreIdentity(
        provider="b2",
        bucket="project-echoes-archive",
        prefix="m7/canonical-schema-v1",
    )
    inventory = inventory_directory(root, identity)
    expectation = InputExpectation(
        identity=identity,
        table_hashes_sha256=_sha256(manifest_bytes),
        expected_inventory_sha256=inventory.sha256,
        expected_object_count=3,
        expected_total_size=inventory.total_size,
    )
    return expectation, files


def test_local_store_materializes_exact_recursive_inventory_and_individual_hashes(
    tmp_path: Path,
) -> None:
    remote_root = tmp_path / "remote"
    expectation, files = _write_canonical_tree(remote_root)
    store = LocalObjectStore(remote_root, identity=expectation.identity)

    assert isinstance(store, ObjectStore)
    inventory = store.inventory()
    assert [item.path for item in inventory.objects] == [
        "indexes/lemma/matrix.npz",
        "lexical_metadata/part-00000.parquet",
        "table-hashes.json",
    ]
    assert all(item.hash_algorithm == "sha256" for item in inventory.objects)
    receipt = materialize_authenticated_input(store, tmp_path / "materialized", expectation)

    assert receipt.identity == expectation.identity
    assert receipt.remote_inventory_sha256 == inventory.sha256
    assert receipt.object_count == 3
    assert dict(receipt.listed_file_sha256) == {
        relative: _sha256(value) for relative, value in files.items()
    }
    assert verify_materialized_input(tmp_path / "materialized", expectation).sha256


def test_materialization_fails_closed_on_identity_inventory_or_file_drift(
    tmp_path: Path,
) -> None:
    remote_root = tmp_path / "remote"
    expectation, _ = _write_canonical_tree(remote_root)
    wrong_store = LocalObjectStore(
        remote_root,
        identity=ObjectStoreIdentity(
            provider="b2",
            bucket="different-bucket",
            prefix="m7/canonical-schema-v1",
        ),
    )
    with pytest.raises(InputAuthenticationError, match="identity differs"):
        materialize_authenticated_input(wrong_store, tmp_path / "wrong", expectation)

    (remote_root / "unexpected.txt").write_text("extra\n", encoding="utf-8")
    store = LocalObjectStore(remote_root, identity=expectation.identity)
    with pytest.raises(InputAuthenticationError, match=r"inventory (SHA-256|count) differs"):
        materialize_authenticated_input(store, tmp_path / "extra", expectation)

    (remote_root / "unexpected.txt").unlink()
    (remote_root / "indexes" / "lemma" / "matrix.npz").write_bytes(b"tampered fixture")
    drifted_inventory = inventory_directory(remote_root, expectation.identity)
    drifted_expectation = InputExpectation(
        identity=expectation.identity,
        table_hashes_sha256=expectation.table_hashes_sha256,
        expected_inventory_sha256=drifted_inventory.sha256,
        expected_object_count=3,
        expected_total_size=drifted_inventory.total_size,
    )
    with pytest.raises(InputAuthenticationError, match="individual file SHA-256 differs"):
        materialize_authenticated_input(
            store,
            tmp_path / "tampered",
            drifted_expectation,
        )


def test_exact_inventory_rejects_unlisted_object_even_without_pinned_inventory_hash(
    tmp_path: Path,
) -> None:
    remote_root = tmp_path / "remote"
    expectation, _ = _write_canonical_tree(remote_root)
    (remote_root / "unlisted.bin").write_bytes(b"unlisted")
    store = LocalObjectStore(remote_root, identity=expectation.identity)
    unpinned_inventory = InputExpectation(
        identity=expectation.identity,
        table_hashes_sha256=expectation.table_hashes_sha256,
    )

    with pytest.raises(InputAuthenticationError, match="remote object inventory differs"):
        materialize_authenticated_input(store, tmp_path / "materialized", unpinned_inventory)


def test_rclone_b2_uses_recursive_hash_inventory_and_environment_only_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_id = "fixture-key-id-do-not-log"
    application_key = "fixture-application-key-do-not-log"
    monkeypatch.setenv("B2_APPLICATION_KEY_ID", key_id)
    monkeypatch.setenv("B2_APPLICATION_KEY", application_key)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_runner(
        argv: Sequence[str],
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append((list(argv), dict(environment)))
        payload = [
            {
                "Path": "nested/artifact.parquet",
                "Size": 7,
                "Hashes": {"SHA-1": "a" * 40},
                "IsDir": False,
            }
        ]
        return subprocess.CompletedProcess(list(argv), 0, json.dumps(payload).encode(), b"")

    store = RcloneB2ObjectStore(
        bucket="project-echoes-archive",
        prefix="m7/canonical-schema-v1",
        runner=fake_runner,
    )
    inventory = store.inventory()

    assert inventory.objects == (
        ObjectInventoryEntry(
            path="nested/artifact.parquet",
            size=7,
            hash_algorithm="sha1",
            digest="a" * 40,
        ),
    )
    argv, environment = calls[0]
    assert "--recursive" in argv
    assert "--files-only" in argv
    assert "--hash" in argv
    assert "echoes_final_discovery_b2:project-echoes-archive/m7/canonical-schema-v1" in argv
    assert key_id not in argv
    assert application_key not in argv
    assert environment["RCLONE_CONFIG_ECHOES_FINAL_DISCOVERY_B2_ACCOUNT"] == key_id
    assert environment["RCLONE_CONFIG_ECHOES_FINAL_DISCOVERY_B2_KEY"] == application_key


def test_rclone_failure_redacts_credentials_and_missing_credentials_fail_before_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_id = "secret-id-value"
    application_key = "secret-key-value"
    monkeypatch.setenv("B2_APPLICATION_KEY_ID", key_id)
    monkeypatch.setenv("B2_APPLICATION_KEY", application_key)
    calls = 0

    def failing_runner(
        argv: Sequence[str],
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            list(argv),
            9,
            b"",
            f"backend echoed {key_id} and {application_key}".encode(),
        )

    store = RcloneB2ObjectStore(
        bucket="project-echoes-archive",
        prefix="results/final-discovery-v1",
        runner=failing_runner,
    )
    with pytest.raises(ObjectStoreError) as captured:
        store.inventory()
    assert calls == 1
    assert key_id not in str(captured.value)
    assert application_key not in str(captured.value)
    assert str(captured.value).count("<redacted>") == 2

    monkeypatch.delenv("B2_APPLICATION_KEY_ID")
    monkeypatch.delenv("B2_APPLICATION_KEY")
    with pytest.raises(ObjectStoreError, match="requires B2_APPLICATION_KEY_ID"):
        store.inventory()
    assert calls == 1


def test_rclone_partial_resume_uses_checksum_and_immutable_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("B2_APPLICATION_KEY_ID", "fixture-id")
    monkeypatch.setenv("B2_APPLICATION_KEY", "fixture-key")
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.bin").write_bytes(b"a")
    (source / "b.bin").write_bytes(b"bb")
    calls: list[list[str]] = []
    inventory_call = 0

    def fake_runner(
        argv: Sequence[str],
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[bytes]:
        del environment
        nonlocal inventory_call
        arguments = list(argv)
        calls.append(arguments)
        if "lsjson" in arguments:
            inventory_call += 1
            entries = [{"Path": "a.bin", "Size": 1, "Hashes": {"SHA-1": "a" * 40}}]
            if inventory_call > 1:
                entries.append({"Path": "b.bin", "Size": 2, "Hashes": {"SHA-1": "b" * 40}})
            return subprocess.CompletedProcess(arguments, 0, json.dumps(entries).encode(), b"")
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    store = RcloneB2ObjectStore(
        bucket="project-echoes-archive",
        prefix="final-discovery-v1/partial",
        runner=fake_runner,
    )

    inventory = store.resume_upload_tree(source)

    assert inventory.object_count == 2
    copy_call = next(arguments for arguments in calls if "copy" in arguments)
    assert "--immutable" in copy_call
    assert "--checksum" in copy_call


def test_deterministic_package_and_exact_local_upload_verification(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "z.txt").write_text("zeta\n", encoding="utf-8")
    (source / "nested" / "a.txt").write_text("alpha\n", encoding="utf-8")
    first = create_deterministic_package(source, tmp_path / "first.tar")
    second = create_deterministic_package(source, tmp_path / "second.tar")

    assert first.archive_sha256 == second.archive_sha256
    assert first.source_inventory_sha256 == second.source_inventory_sha256
    verify_package(first)
    first.archive_path.write_bytes(b"tampered package")
    with pytest.raises(InputAuthenticationError, match=r"package (size|SHA-256) differs"):
        verify_package(first)

    upload_source = tmp_path / "upload-source"
    upload_source.mkdir()
    (upload_source / "second.tar").write_bytes(second.archive_path.read_bytes())
    remote = LocalObjectStore(
        tmp_path / "uploaded",
        identity=ObjectStoreIdentity(
            provider="b2",
            bucket="project-echoes-archive",
            prefix="final-discovery-v1/packages/run-fixture",
        ),
    )
    receipt = upload_and_verify_tree(remote, upload_source)
    assert receipt.object_count == 1
    assert receipt.total_size == second.archive_size
    assert receipt.local_inventory_sha256 == receipt.remote_inventory_sha256
    with pytest.raises(ObjectStoreConflictError, match="nonempty object-store prefix"):
        upload_and_verify_tree(remote, upload_source)


def test_exact_partial_upload_resumes_without_replacing_existing_objects(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"preserved\n")
    (source / "b.txt").write_bytes(b"resumed\n")
    remote_root = tmp_path / "remote"
    remote_root.mkdir()
    existing = remote_root / "a.txt"
    existing.write_bytes(b"preserved\n")
    original_stat = existing.stat()
    remote = LocalObjectStore(
        remote_root,
        identity=ObjectStoreIdentity(
            provider="b2",
            bucket="project-echoes-archive",
            prefix="final-discovery-v1/partial",
        ),
    )

    receipt, action = resume_or_upload_and_verify_tree(remote, source)

    assert action == "resumed_partial"
    assert receipt.object_count == 2
    assert existing.stat().st_ino == original_stat.st_ino
    assert existing.read_bytes() == b"preserved\n"
    assert (remote_root / "b.txt").read_bytes() == b"resumed\n"


def test_partial_upload_conflict_is_preserved_and_blocks_resume(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"expected\n")
    (source / "b.txt").write_bytes(b"missing\n")
    remote_root = tmp_path / "remote"
    remote_root.mkdir()
    conflicting = remote_root / "a.txt"
    conflicting.write_bytes(b"conflict\n")
    remote = LocalObjectStore(remote_root)

    with pytest.raises(ObjectStoreConflictError, match="object hash differs"):
        resume_or_upload_and_verify_tree(remote, source)

    assert conflicting.read_bytes() == b"conflict\n"
    assert not (remote_root / "b.txt").exists()


def test_package_never_silently_overwrites(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "artifact.txt").write_text("artifact\n", encoding="utf-8")
    destination = tmp_path / "result.tar"
    destination.write_bytes(b"preexisting")

    with pytest.raises(ObjectStoreConflictError, match="refusing to replace"):
        create_deterministic_package(source, destination)
    assert destination.read_bytes() == b"preexisting"
