from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE_REF = "${{ inputs.ref || github.event.release.tag_name }}"


def _load_workflow(name: str) -> dict[str, Any]:
    workflow = ROOT / ".github" / "workflows" / name
    return yaml.load(workflow.read_text(), Loader=yaml.BaseLoader)


def _find_action_step(steps: list[dict[str, Any]], action: str) -> dict[str, Any]:
    for step in steps:
        if action in str(step.get("uses", "")):
            return step
    raise AssertionError(f"missing action step matching {action!r}")


def test_release_distribution_artifact_name_is_unique_to_release_workflow() -> None:
    workflow = _load_workflow("release.yml")
    upload_step = _find_action_step(workflow["jobs"]["build"]["steps"], "actions/upload-artifact")

    artifact_name = upload_step["with"]["name"]

    assert artifact_name == "release-dist"
    assert artifact_name != "dist"
    for job_name in ("publish-testpypi", "publish-pypi"):
        download_step = _find_action_step(workflow["jobs"][job_name]["steps"], "actions/download-artifact")
        assert download_step["with"]["name"] == artifact_name


def test_release_reusable_ci_and_build_jobs_use_target_ref() -> None:
    workflow = _load_workflow("release.yml")

    assert workflow["jobs"]["ci"]["with"]["ref"] == RELEASE_REF
    for job_name in ("verify-version", "build"):
        checkout_step = _find_action_step(workflow["jobs"][job_name]["steps"], "actions/checkout")
        assert checkout_step["with"]["ref"] == RELEASE_REF


def test_ci_required_gate_includes_pr_only_jobs_with_skip_handling() -> None:
    workflow = _load_workflow("ci.yml")
    required = workflow["jobs"]["required"]

    assert {"docs-build", "dependency-review"}.issubset(set(required["needs"]))

    gate_step = required["steps"][0]
    gate_script = gate_step["run"]
    assert "GITHUB_EVENT_NAME" in gate_script
    assert "docs-build" in gate_script
    assert "dependency-review" in gate_script
