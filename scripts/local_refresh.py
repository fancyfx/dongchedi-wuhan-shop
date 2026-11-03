#!/usr/bin/env python3
"""Run the complete vehicle-data refresh locally.

This replaces the former GitHub Actions data workflow. It performs, in order:
1. prepare/update AutoHome current + historical repositories under .external/;
2. rebuild exact-trim configuration from vault/main identity + live autohome.com.cn config pages;
3. recalculate rankings and data-issue routing;
4. run regression tests;
5. build the dashboard;
6. clean stale legacy config metadata and validate generated artifacts.

The script never commits or pushes automatically. Review `git diff` and commit
all generated data/code changes together after a successful run.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / ".external"
AUTOHOME_MAIN = EXTERNAL / "autohome-main"
AUTOHOME_VAULTS = EXTERNAL / "autohome-vaults"
AUTOHOME_URL = "https://github.com/swoiow/autohome.git"
INDEX = ROOT / "data" / "vehicle-specs-verified.json"
REPORT = ROOT / "data" / "specs" / "exact-trim-sync-report.json"
META = ROOT / "data" / "meta.json"
DASH_META = ROOT / "dashboard" / "public" / "data" / "meta.json"
LEGACY_SHARDS = [ROOT / "data" / "specs" / f"exact-trims-{i}.json" for i in range(1, 5)]


def run(*args: str, cwd: Path | None = None) -> None:
    print("+", " ".join(args))
    subprocess.run(args, cwd=str(cwd or ROOT), check=True)


def capture(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=str(cwd or ROOT), text=True).strip()


def ensure_program(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"required program not found: {name}")


def ensure_zstandard() -> None:
    try:
        import zstandard  # noqa: F401
    except ImportError:
        cmd = [sys.executable, "-m", "pip", "install", "zstandard>=0.25,<0.26"]
        try:
            subprocess.run(cmd, cwd=str(ROOT), check=True)
        except subprocess.CalledProcessError:
            subprocess.run(cmd + ["--break-system-packages"], cwd=str(ROOT), check=True)


def prepare_main_repo() -> None:
    if not (AUTOHOME_MAIN / ".git").exists():
        EXTERNAL.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--depth", "1", "--branch", "main", AUTOHOME_URL, str(AUTOHOME_MAIN))
        return
    run("git", "fetch", "--depth", "1", "origin", "main", cwd=AUTOHOME_MAIN)
    run("git", "checkout", "-B", "main", "FETCH_HEAD", cwd=AUTOHOME_MAIN)


def prepare_vault_repo() -> None:
    # Full depth-1 checkout is only ~100MB and avoids promisor on-demand blob
    # fetches that made historical exact-trim matching unusably slow.
    if not (AUTOHOME_VAULTS / ".git").exists():
        EXTERNAL.mkdir(parents=True, exist_ok=True)
        run(
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "vaults",
            AUTOHOME_URL,
            str(AUTOHOME_VAULTS),
        )
        return
    run("git", "fetch", "--depth", "1", "origin", "vaults", cwd=AUTOHOME_VAULTS)
    run("git", "checkout", "-B", "vaults", "FETCH_HEAD", cwd=AUTOHOME_VAULTS)


def prepare_live_runtime() -> None:
    """Chrome + puppeteer-core used to decode live AutoHome config pages."""
    try:
        import autohome_live_config as live
    except Exception as exc:
        raise SystemExit(f"autohome live config helper import failed: {exc}") from exc
    live.ensure_runtime()
    print("AutoHome live fetch runtime ready (Chrome + puppeteer-core)")


def prepare_sources() -> None:
    ensure_program("git")
    ensure_zstandard()
    prepare_main_repo()
    prepare_vault_repo()
    prepare_live_runtime()
    print("AutoHome main:", capture("git", "rev-parse", "HEAD", cwd=AUTOHOME_MAIN))
    print("AutoHome vaults:", capture("git", "rev-parse", "HEAD", cwd=AUTOHOME_VAULTS))


def clean_legacy_meta() -> None:
    if not META.exists():
        return
    meta = json.loads(META.read_text(encoding="utf-8"))
    for key in ("specs_coverage", "morning_check_weights", "morning_check_note"):
        meta.pop(key, None)

    meta["configuration_generation"] = "new_full_exact_trim_only"
    meta["configuration_source_policy"] = (
        "AutoHome live config pages preferred for parameters; vault/main CSV for exact-trim identity; legacy/approximate forbidden"
    )
    meta["configuration_refresh_mode"] = "local_only"
    meta["configuration_refresh_command"] = "python3 scripts/local_refresh.py"
    meta["legacy_configuration_compatible"] = False
    meta["config_scoring"] = {
        "method": "exact_trim_full_parameters",
        "approximate_fallback": False,
        "legacy_shards_allowed": False,
        "min_scoring_coverage": 0.60,
    }

    text = json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    META.write_text(text, encoding="utf-8")
    if DASH_META.parent.exists():
        DASH_META.write_text(text, encoding="utf-8")


def validate_new_only_policy() -> None:
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert index.get("trim_files") == ["specs/exact-trims-auto.json"], index.get("trim_files")
    mapping = {str(k): str(v) for k, v in (index.get("sku_to_trim") or {}).items()}
    invalid = {k: v for k, v in mapping.items() if not v.startswith("trim_ah_")}
    assert not invalid, list(invalid.items())[:5]
    assert not any(path.exists() for path in LEGACY_SHARDS), "legacy exact-trim shard still exists"

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report.get("total_listings") is not None
    assert int(report.get("newly_matched") or 0) == len(mapping), (report.get("newly_matched"), len(mapping))

    ranked = json.loads((ROOT / "data" / "listings-ranked.json").read_text(encoding="utf-8"))
    issues = json.loads((ROOT / "data" / "data-issues.json").read_text(encoding="utf-8"))
    filtered = json.loads((ROOT / "data" / "listings-filtered.json").read_text(encoding="utf-8"))
    assert len(filtered) == len(ranked) + len(issues)
    assert all(x.get("score_eligible") is True for x in ranked)
    assert all(x.get("score_eligible") is False for x in issues)
    print(
        f"validated new-only config: mapped={len(mapping)} ranked={len(ranked)} "
        f"issues={len(issues)} filtered={len(filtered)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-source-update",
        action="store_true",
        help="reuse already prepared .external/autohome-* repositories",
    )
    parser.add_argument(
        "--skip-dashboard-build",
        action="store_true",
        help="skip npm ci / npm run build",
    )
    args = parser.parse_args()

    if not args.skip_source_update:
        prepare_sources()
    else:
        ensure_zstandard()
        if not (AUTOHOME_MAIN / ".git").exists() or not (AUTOHOME_VAULTS / ".git").exists():
            raise SystemExit("--skip-source-update requested but .external AutoHome repos are missing")
        prepare_live_runtime()

    env = os.environ.copy()
    env["AUTOHOME_MAIN_REPO"] = str(AUTOHOME_MAIN)
    env["AUTOHOME_VAULTS_REPO"] = str(AUTOHOME_VAULTS)
    print(f"AUTOHOME_MAIN_REPO={AUTOHOME_MAIN}")
    print(f"AUTOHOME_VAULTS_REPO={AUTOHOME_VAULTS}")

    def run_env(*cmd: str, cwd: Path | None = None) -> None:
        print("+", " ".join(cmd))
        subprocess.run(cmd, cwd=str(cwd or ROOT), env=env, check=True)

    run(sys.executable, "scripts/tests/test_autohome_sync.py")
    run(sys.executable, "scripts/tests/test_autohome_rules.py")
    run(sys.executable, "scripts/tests/test_autohome_live.py")
    run_env(sys.executable, "scripts/sync_exact_trim_specs_strict.py")
    run(sys.executable, "scripts/rerank_v2.py")
    clean_legacy_meta()
    run(sys.executable, "scripts/tests/test_ranking_v2.py")
    validate_new_only_policy()

    import autohome_live_config as live_cfg

    live_cfg.export_live_config_trees()

    if not args.skip_dashboard_build:
        ensure_program("npm")
        run("npm", "ci", cwd=ROOT / "dashboard")
        run("npm", "run", "build", cwd=ROOT / "dashboard")

    print("\nLocal refresh completed successfully.")
    print("Review generated changes with: git status && git diff --stat")
    print("Do not reintroduce data-fetch/rerank GitHub Actions.")


if __name__ == "__main__":
    main()
