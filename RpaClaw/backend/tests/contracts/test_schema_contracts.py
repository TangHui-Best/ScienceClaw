import hashlib
import json
from pathlib import Path
from typing import NoReturn

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource


CONTRACT_ROOT = Path(__file__).resolve().parent
SCHEMA_ROOT = CONTRACT_ROOT / "schemas"
GOLDEN_ROOT = CONTRACT_ROOT / "golden" / "first_e2e"
KNOWN_DRIFT_ROOT = CONTRACT_ROOT / "fixtures" / "known-drift"
SNAPSHOT_SHA256_PATH = CONTRACT_ROOT / "snapshot-sha256.json"

SCHEMA_PATHS = {
    "core_trace": SCHEMA_ROOT / "core-trace-timeline-v0.1.schema.json",
    "skill_definition": SCHEMA_ROOT / "skill-definition-v0.1.schema.json",
    "skill_manifest": SCHEMA_ROOT / "skill-manifest-v0.1.schema.json",
}


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _deny_external_retrieval(uri: str) -> NoReturn:
    raise AssertionError(f"schema validation attempted external retrieval: {uri}")


@pytest.fixture(scope="module")
def schema_contracts() -> tuple[dict[str, dict], Registry]:
    schemas = {name: _load_json(path) for name, path in SCHEMA_PATHS.items()}
    registry = Registry(retrieve=_deny_external_retrieval)
    for schema in schemas.values():
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema)
        )
    return schemas, registry


def test_schema_snapshots_are_valid_draft_2020_12(
    schema_contracts: tuple[dict[str, dict], Registry],
) -> None:
    schemas, _ = schema_contracts

    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)


def test_schema_and_golden_snapshot_hashes_are_locked() -> None:
    expected_hashes = _load_json(SNAPSHOT_SHA256_PATH)
    expected_paths = {
        "schemas/core-trace-timeline-v0.1.schema.json",
        "schemas/skill-definition-v0.1.schema.json",
        "schemas/skill-manifest-v0.1.schema.json",
        "golden/first_e2e/coretrace.timeline.json",
        "golden/first_e2e/skill.definition.json",
        "golden/first_e2e/generated-skill/skill.manifest.json",
        "golden/first_e2e/replay-a.inputs.json",
        "golden/first_e2e/replay-b.inputs.json",
    }

    assert set(expected_hashes) == expected_paths
    for relative_path, expected_hash in expected_hashes.items():
        snapshot_path = CONTRACT_ROOT / relative_path
        actual_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, relative_path


@pytest.mark.parametrize(
    ("schema_name", "instance_path"),
    [
        (
            "core_trace",
            GOLDEN_ROOT / "coretrace.timeline.json",
        ),
        (
            "skill_definition",
            GOLDEN_ROOT / "skill.definition.json",
        ),
        (
            "skill_manifest",
            GOLDEN_ROOT / "generated-skill" / "skill.manifest.json",
        ),
    ],
)
def test_first_e2e_golden_instances_match_repository_schema_snapshots(
    schema_name: str,
    instance_path: Path,
    schema_contracts: tuple[dict[str, dict], Registry],
) -> None:
    schemas, registry = schema_contracts
    validator = Draft202012Validator(schemas[schema_name], registry=registry)

    validator.validate(_load_json(instance_path))


def test_known_drift_skill_definition_fixture_is_rejected_by_schema(
    schema_contracts: tuple[dict[str, dict], Registry],
) -> None:
    schemas, registry = schema_contracts
    validator = Draft202012Validator(
        schemas["skill_definition"], registry=registry
    )

    errors = validator.iter_errors(
        _load_json(
            KNOWN_DRIFT_ROOT
            / "skill-definition-stage3-and-missing-assets.json"
        )
    )
    error_facts = [
        (error.validator, tuple(error.absolute_path), error.message)
        for error in errors
    ]

    assert any(
        validator_name == "additionalProperties"
        and path == ()
        and "stage_3_notification" in message
        for validator_name, path, message in error_facts
    )
    for required_property in ("asset_inputs", "asset_outputs"):
        assert any(
            validator_name == "required"
            and path == ()
            and required_property in message
            for validator_name, path, message in error_facts
        )


def test_known_drift_skill_manifest_fixture_is_rejected_by_schema(
    schema_contracts: tuple[dict[str, dict], Registry],
) -> None:
    schemas, registry = schema_contracts
    validator = Draft202012Validator(schemas["skill_manifest"], registry=registry)

    errors = validator.iter_errors(
        _load_json(
            KNOWN_DRIFT_ROOT / "skill-manifest-missing-assets.json"
        )
    )
    error_facts = [
        (error.validator, tuple(error.absolute_path), error.message)
        for error in errors
    ]

    for required_property in ("asset_inputs", "asset_outputs"):
        assert any(
            validator_name == "required"
            and path == ()
            and required_property in message
            for validator_name, path, message in error_facts
        )


@pytest.mark.parametrize(
    ("replay_name", "fixture_profile"),
    [("replay-a.inputs.json", "A"), ("replay-b.inputs.json", "B")],
)
def test_replay_inputs_cover_all_required_skill_inputs(
    replay_name: str, fixture_profile: str
) -> None:
    skill_definition = _load_json(GOLDEN_ROOT / "skill.definition.json")
    replay = _load_json(GOLDEN_ROOT / replay_name)
    required_inputs = {
        item["ref"] for item in skill_definition["inputs"] if item["required"]
    }

    assert replay["fixture_profile"] == fixture_profile
    assert set(replay["inputs"]) == required_inputs
