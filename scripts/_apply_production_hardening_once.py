#!/usr/bin/env python3
"""Apply one exact temporary launch-hardening patch, then remove this file."""

from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0 and new in text:
        return text
    raise SystemExit(f"{label} drifted: old_count={count}, new_present={new in text}")


def patch_launcher() -> None:
    path = Path("cloud/launch_final_discovery.sh")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        """Usage: sudo bash /srv/project-echoes/repo/cloud/launch_final_discovery.sh

Fail-closed owner launcher for the single final-discovery-v1 production
worker. It never provisions, purchases, stops, deletes, or polls a cloud
resource. It starts one detached systemd service, takes one startup snapshot,
and exits.
""",
        """Usage:
  sudo bash /srv/project-echoes/repo/cloud/launch_final_discovery.sh --preflight-only
  sudo bash /srv/project-echoes/repo/cloud/launch_final_discovery.sh

Fail-closed owner launcher for the single final-discovery-v1 production
worker. Preflight performs every local, budget, model, M7 identity, credential,
and output-namespace check but never creates a service or launch record. Launch
starts one detached systemd service, takes one startup snapshot, and exits. The
script never provisions, purchases, stops, deletes, or polls a cloud resource.
""",
        label="launcher usage",
    )
    text = replace_once(
        text,
        """if (($#)); then
    case "$1" in
        -h|--help)
            (($# == 1)) || { usage >&2; exit 2; }
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
fi
""",
        """launch_mode="launch"
if (($#)); then
    case "$1" in
        --preflight-only)
            (($# == 1)) || { usage >&2; exit 2; }
            launch_mode="preflight"
            ;;
        -h|--help)
            (($# == 1)) || { usage >&2; exit 2; }
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
fi
""",
        label="launcher argument parser",
    )
    text = replace_once(
        text,
        """    ECHOES_SERVER_CREATED_AT_UTC
    ECHOES_B2_COST_RESERVE_USD
""",
        """    ECHOES_SERVER_CREATED_AT_UTC
    ECHOES_ACCRUED_INFRASTRUCTURE_USD
    ECHOES_ACCRUED_COST_VERIFIED_AT_UTC
    ECHOES_B2_COST_RESERVE_USD
""",
        label="required environment inventory",
    )
    text = replace_once(
        text,
        """    ECHOES_FINAL_DISCOVERY_DISK_FLOOR_GIB ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS
    ECHOES_HARD_BUDGET_USD
""",
        """    ECHOES_FINAL_DISCOVERY_DISK_FLOOR_GIB ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS
    ECHOES_HARD_BUDGET_USD ECHOES_ACCRUED_INFRASTRUCTURE_USD
    ECHOES_ACCRUED_COST_VERIFIED_AT_UTC
""",
        label="metadata environment inventory",
    )

    start_marker = 'budget_json="$(python3 - \\\n'
    end_marker = "\n\ngit_as_service="
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise SystemExit("launcher budget block boundary drifted")
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    budget = r'''budget_json="$(python3 - \
    "$ECHOES_VERIFIED_RATE_USD_PER_HOUR" \
    "$ECHOES_RATE_VERIFIED_AT_UTC" \
    "$ECHOES_SERVER_CREATED_AT_UTC" \
    "$ECHOES_ACCRUED_INFRASTRUCTURE_USD" \
    "$ECHOES_ACCRUED_COST_VERIFIED_AT_UTC" \
    "$ECHOES_B2_COST_RESERVE_USD" \
    "$ECHOES_HARD_BUDGET_USD" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation


def timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"{label} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise SystemExit(f"{label} must include the UTC offset")
    return parsed.astimezone(UTC)


try:
    rate = Decimal(sys.argv[1])
    accrued = Decimal(sys.argv[4])
    reserve = Decimal(sys.argv[6])
    cap = Decimal(sys.argv[7])
except InvalidOperation as exc:
    raise SystemExit("rate, accrued cost, B2 reserve, and budget must be decimals") from exc
if rate <= 0 or accrued < 0 or reserve < 0 or cap != Decimal("75.00"):
    raise SystemExit("invalid rate, accrued cost, B2 reserve, or frozen budget")

now = datetime.now(UTC)
rate_verified_at = timestamp(sys.argv[2], "rate verification")
created_at = timestamp(sys.argv[3], "server creation")
accrued_verified_at = timestamp(sys.argv[5], "accrued-cost verification")
for verified_at, label in (
    (rate_verified_at, "all-in hourly rate"),
    (accrued_verified_at, "accrued infrastructure cost"),
):
    if verified_at > now + timedelta(minutes=5) or now - verified_at > timedelta(hours=24):
        raise SystemExit(f"the owner must reverify the {label} within 24 hours of launch")
if created_at > now + timedelta(minutes=5):
    raise SystemExit("server creation time cannot be in the future")

worker_hours = Decimal("96")
projected_future_infrastructure = worker_hours * rate
projected_all_in = accrued + projected_future_infrastructure + reserve
if projected_all_in > cap:
    raise SystemExit("verified accrued cost plus worker window and B2 reserve exceeds $75")
print(
    json.dumps(
        {
            "verified_rate_usd_per_hour": str(rate),
            "rate_verified_at_utc": rate_verified_at.isoformat(),
            "server_created_at_utc": created_at.isoformat(),
            "verified_accrued_infrastructure_usd": str(accrued),
            "accrued_cost_verified_at_utc": accrued_verified_at.isoformat(),
            "maximum_worker_hours": 96,
            "projected_future_infrastructure_usd": str(
                projected_future_infrastructure.quantize(Decimal("0.001"))
            ),
            "b2_cost_reserve_usd": str(reserve),
            "projected_all_in_usd": str(projected_all_in.quantize(Decimal("0.001"))),
            "hard_cap_usd": str(cap),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
)
PY
)" || die "current owner-verified pricing does not fit the frozen $75 all-in cap"'''
    text = text[:start] + budget + text[end:]

    output_marker = ''')" || die "B2 output namespace is neither empty nor an authenticated resumable state"

launch_id="$(date -u +%Y%m%dT%H%M%SZ)-${observed_commit:0:12}"'''
    hardened_output = r''')" || die "B2 output namespace is neither empty nor an authenticated resumable state"

# Authenticate the exact remote M7 identity without downloading its 17 GiB
# body. Stage 1 still downloads every object and verifies every manifest-listed
# SHA-256 before analysis. This preflight catches credentials, bucket/prefix,
# remote inventory, and manifest-identity errors before a worker can start.
m7_preflight_json="$(
    while IFS= read -r exported_name; do
        case "$exported_name" in
            PATH|LANG|LC_*) ;;
            *) export -n "$exported_name" ;;
        esac
    done < <(compgen -e)
    export B2_APPLICATION_KEY_ID B2_APPLICATION_KEY
    runuser -u "$ECHOES_SERVICE_USER" --preserve-environment -- sh -c \
        'cd -- "$1" && exec "$2" run --frozen --no-sync python - "$3" "$4" "$5"' \
        sh "$ECHOES_REPO_ROOT" "$ECHOES_UV_BIN" "$ECHOES_M7_BUCKET" \
        "$ECHOES_M7_PREFIX" "$M7_MANIFEST_SHA256" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys

from echoes.final_discovery.inputs import RcloneB2ObjectStore

bucket, prefix, expected_manifest_sha256 = sys.argv[1:]
store = RcloneB2ObjectStore(bucket=bucket, prefix=prefix)
inventory = store.inventory()
manifest = store.read_bytes("table-hashes.json", maximum_bytes=64 * 1024 * 1024)
observed_manifest_sha256 = hashlib.sha256(manifest).hexdigest()
if observed_manifest_sha256 != expected_manifest_sha256:
    raise SystemExit(
        "remote M7 table-hashes.json differs: "
        f"expected={expected_manifest_sha256}, observed={observed_manifest_sha256}"
    )
if inventory.object_count != 18_606 or inventory.total_size != 18_413_699_180:
    raise SystemExit(
        "remote M7 object inventory differs from the verified archive: "
        f"objects={inventory.object_count}, bytes={inventory.total_size}"
    )
print(
    json.dumps(
        {
            "identity": inventory.identity.canonical_uri,
            "object_count": inventory.object_count,
            "total_size": inventory.total_size,
            "table_hashes_sha256": observed_manifest_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
)
PY
)" || die "canonical M7 remote identity or credentials failed preflight"

if [[ "$launch_mode" == preflight ]]; then
    python3 - "$observed_commit" "$available_bytes" "$budget_json" \
        "$m7_preflight_json" "$output_namespace_json" <<'PY'
from __future__ import annotations

import json
import sys

commit, available_bytes, budget, m7, output_namespace = sys.argv[1:]
print(
    json.dumps(
        {
            "schema_version": 1,
            "experiment_id": "final-discovery-v1",
            "preflight_passed": True,
            "service_created": False,
            "git_commit": commit,
            "available_bytes": int(available_bytes),
            "budget": json.loads(budget),
            "m7": json.loads(m7),
            "output_namespace": json.loads(output_namespace),
        },
        indent=2,
        sort_keys=True,
    )
)
PY
    printf 'FINAL_DISCOVERY_PREFLIGHT_COMPLETE\n'
    exit 0
fi

launch_id="$(date -u +%Y%m%dT%H%M%SZ)-${observed_commit:0:12}"'''
    text = replace_once(
        text,
        output_marker,
        hardened_output,
        label="B2 and no-service preflight insertion",
    )
    path.write_text(text, encoding="utf-8")


def patch_adapter() -> None:
    path = Path("cloud/launch_final_discovery_scaleway.sh")
    text = path.read_text(encoding="utf-8")
    replacements = (
        ("authorized 80-hour operational stop", "authorized 68-hour operational stop"),
        (
            "require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 80",
            "require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 68",
        ),
        ('worker_hours = Decimal("80")', 'worker_hours = Decimal("68")'),
        ('"maximum_worker_hours": 80,', '"maximum_worker_hours": 68,'),
        ("--property=RuntimeMaxSec=80h", "--property=RuntimeMaxSec=68h"),
        ('exec bash "$adapter"', 'exec bash "$adapter" "$@"'),
    )
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new)
        elif new not in text:
            raise SystemExit(f"Scaleway adapter token drifted: {old}")
    path.write_text(text, encoding="utf-8")


def patch_environment_examples() -> None:
    path = Path("cloud/final-discovery.env.example")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """ECHOES_SERVER_CREATED_AT_UTC=OWNER_SET_UTC_TIMESTAMP
ECHOES_B2_COST_RESERVE_USD=10.00
""",
        """ECHOES_SERVER_CREATED_AT_UTC=OWNER_SET_UTC_TIMESTAMP
# Current cumulative infrastructure cost for this campaign, rounded upward
# rather than down. Reverify it at the timestamp below before launch.
ECHOES_ACCRUED_INFRASTRUCTURE_USD=OWNER_SET_CONSERVATIVE_CURRENT_TOTAL
ECHOES_ACCRUED_COST_VERIFIED_AT_UTC=OWNER_SET_UTC_TIMESTAMP
ECHOES_B2_COST_RESERVE_USD=10.00
""",
        label="base environment example cost fields",
    )
    path.write_text(text, encoding="utf-8")

    Path("cloud/final-discovery-scaleway.env.example").write_text(
        """# Root-owned Scaleway production environment for final-discovery-v1.
# Copy to /etc/project-echoes/final-discovery.env, replace every OWNER_SET
# value, then chown root:root and chmod 600. Keep values unquoted.

ECHOES_AUTHORIZE_PRODUCTION=final-discovery-v1
ECHOES_EXPECTED_SERVER_TYPE=POP2-16C-64G
ECHOES_SERVER_NAME=project-echoes-final-discovery
ECHOES_REPO_ROOT=/srv/project-echoes/repo
ECHOES_WORK_DIR=/srv/project-echoes/final-discovery/work
ECHOES_PREPARED_PASSAGES=/srv/project-echoes/inputs/final-discovery/passages.jsonl
ECHOES_KNOWNNESS_PATH=/srv/project-echoes/inputs/final-discovery/known-relationships.jsonl
ECHOES_MODEL_ROOT=/srv/project-echoes/models/intfloat-multilingual-e5-small-614241f622f5
ECHOES_UV_BIN=/usr/local/bin/uv
ECHOES_SERVICE_USER=echoes
ECHOES_SERVICE_GROUP=echoes
ECHOES_EXPECTED_GIT_COMMIT=OWNER_SET_EXACT_GIT_COMMIT
ECHOES_M7_BUCKET=project-echoes-archive
ECHOES_M7_PREFIX=m7/canonical-schema-v1
ECHOES_M7_MANIFEST_SHA256=e56a1d3ee4f9707c17e7a25dc6b3d82ad5ec9a9bb28234762d58179142ebf6b6
ECHOES_OUTPUT_BUCKET=project-echoes-archive
ECHOES_OUTPUT_PREFIX=OWNER_SET_UNIQUE_EMPTY_OUTPUT_PREFIX
B2_APPLICATION_KEY_ID=OWNER_SET_B2_APPLICATION_KEY_ID
B2_APPLICATION_KEY=OWNER_SET_B2_APPLICATION_KEY
ECHOES_FINAL_DISCOVERY_THREADS=12
ECHOES_FINAL_DISCOVERY_PROCESS_MEMORY_GIB=56
ECHOES_FINAL_DISCOVERY_DUCKDB_MEMORY_LIMIT_GIB=40
ECHOES_FINAL_DISCOVERY_INITIAL_FREE_DISK_GIB=280
ECHOES_FINAL_DISCOVERY_DISK_FLOOR_GIB=80
ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS=68
ECHOES_HARD_BUDGET_USD=75.00
# All-in running rate in USD/hour for compute, Block Storage, and flexible IPv4.
ECHOES_VERIFIED_RATE_USD_PER_HOUR=OWNER_SET_CURRENT_ALL_IN_USD_RATE
ECHOES_RATE_VERIFIED_AT_UTC=OWNER_SET_UTC_TIMESTAMP
ECHOES_SERVER_CREATED_AT_UTC=2026-08-25T22:16:16Z
# Current cumulative Scaleway campaign cost, rounded upward.
ECHOES_ACCRUED_INFRASTRUCTURE_USD=OWNER_SET_CONSERVATIVE_CURRENT_TOTAL
ECHOES_ACCRUED_COST_VERIFIED_AT_UTC=OWNER_SET_UTC_TIMESTAMP
ECHOES_B2_COST_RESERVE_USD=10.00
""",
        encoding="utf-8",
    )


def patch_tests() -> None:
    cloud_path = Path("tests/unit/test_final_discovery_cloud_scripts.py")
    cloud = cloud_path.read_text(encoding="utf-8")
    cloud = replace_once(
        cloud,
        '        "ECHOES_SERVER_CREATED_AT_UTC",\n',
        (
            '        "ECHOES_SERVER_CREATED_AT_UTC",\n'
            '        "ECHOES_ACCRUED_INFRASTRUCTURE_USD",\n'
            '        "ECHOES_ACCRUED_COST_VERIFIED_AT_UTC",\n'
        ),
        label="cloud-script environment fields test",
    )
    cloud_path.write_text(cloud, encoding="utf-8")

    adapter_path = Path("tests/unit/test_final_discovery_scaleway_adapter.py")
    adapter = adapter_path.read_text(encoding="utf-8")
    for old, new in (
        (
            "require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 80",
            "require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 68",
        ),
        ('worker_hours = Decimal("80")', 'worker_hours = Decimal("68")'),
        ('"maximum_worker_hours": 80,', '"maximum_worker_hours": 68,'),
        ("--property=RuntimeMaxSec=80h", "--property=RuntimeMaxSec=68h"),
    ):
        adapter = adapter.replace(old, new)
    adapter_path.write_text(adapter, encoding="utf-8")

    Path("tests/unit/test_final_discovery_launch_hardening.py").write_text(
        '''"""Cost and preflight contracts for the production owner launcher."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "cloud" / "launch_final_discovery.sh"
ADAPTER = ROOT / "cloud" / "launch_final_discovery_scaleway.sh"
SCALEWAY_ENV = ROOT / "cloud" / "final-discovery-scaleway.env.example"


def test_launcher_has_true_no_service_preflight_boundary() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    assert "--preflight-only" in script
    assert 'if [[ "$launch_mode" == preflight ]]; then' in script
    assert "FINAL_DISCOVERY_PREFLIGHT_COMPLETE" in script
    assert '"service_created": False' in script
    assert script.index('if [[ "$launch_mode" == preflight ]]; then') < script.index(
        'launch_id="$(date -u'
    )


def test_preflight_authenticates_exact_m7_remote_identity() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    assert "inventory.object_count != 18_606" in script
    assert "inventory.total_size != 18_413_699_180" in script
    assert "remote M7 table-hashes.json differs" in script
    assert "canonical M7 remote identity or credentials failed preflight" in script


def test_budget_uses_verified_accrued_cost_not_server_wall_clock() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")
    assert "ECHOES_ACCRUED_INFRASTRUCTURE_USD" in script
    assert "ECHOES_ACCRUED_COST_VERIFIED_AT_UTC" in script
    assert "projected_all_in = accrued + projected_future_infrastructure + reserve" in script
    assert "accrued_hours" not in script


def test_scaleway_adapter_caps_worker_at_68_hours_and_forwards_preflight() -> None:
    adapter = ADAPTER.read_text(encoding="utf-8")
    assert "require_exact ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS 68" in adapter
    assert 'worker_hours = Decimal("68")' in adapter
    assert '"maximum_worker_hours": 68,' in adapter
    assert "--property=RuntimeMaxSec=68h" in adapter
    assert 'exec bash "$adapter" "$@"' in adapter


def test_scaleway_environment_template_contains_every_cost_input() -> None:
    example = SCALEWAY_ENV.read_text(encoding="utf-8")
    for token in (
        "ECHOES_EXPECTED_SERVER_TYPE=POP2-16C-64G",
        "ECHOES_FINAL_DISCOVERY_RUNTIME_HOURS=68",
        "ECHOES_ACCRUED_INFRASTRUCTURE_USD=",
        "ECHOES_ACCRUED_COST_VERIFIED_AT_UTC=",
        "ECHOES_B2_COST_RESERVE_USD=10.00",
    ):
        assert token in example
''',
        encoding="utf-8",
    )


def main() -> None:
    patch_launcher()
    patch_adapter()
    patch_environment_examples()
    patch_tests()


if __name__ == "__main__":
    main()
