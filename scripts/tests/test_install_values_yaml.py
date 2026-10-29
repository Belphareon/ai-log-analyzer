from pathlib import Path
import os
import shutil
import subprocess

import pytest
import yaml


def test_install_values_heredoc_is_valid_yaml():
    install_script = Path(__file__).parents[2] / "install.sh"
    source = install_script.read_text(encoding="utf-8")
    start_marker = 'cat > "$INFRA_APPS_DIR/values.yaml" << VALEOF\n'
    start = source.index(start_marker) + len(start_marker)
    end = source.index("\nVALEOF", start)

    values = yaml.safe_load(source[start:end])

    assert values["env"]["DB_DDL_ROLE"] == "$DB_DDL_ROLE"
    assert values["env"]["MONITORED_NAMESPACES"] == "$MONITORED_NAMESPACES"
    assert values["init"]["forceThresholdRefresh"] == "${INIT_FORCE_THRESHOLD_REFRESH:-false}"
    assert values["init"]["bootstrap"] == "${INIT_BOOTSTRAP:-false}"
    assert values["init"]["quiesce"] == "${INIT_QUIESCE:-false}"
    assert values["init"]["thresholdWeeks"] == "${INIT_THRESHOLD_WEEKS:-12}"
    assert values["env"]["PERCENTILE_LEVEL"] == "${PERCENTILE_LEVEL:-0.95}"
    assert values["scratch"]["mountPath"] == "/scratch"
    assert values["persistence"]["storageSize"] == "$PERSISTENCE_STORAGE_SIZE"
    assert values["email"]["smtpHost"] == "${SMTP_HOST:-css-smtp-prod-os.sos.kb.cz}"
    assert values["teams"]["enabled"] == "${TEAMS_ENABLED:-false}"


@pytest.mark.parametrize("configured,expected", [("", "40Gi"), ("60Gi", "60Gi")])
def test_installer_preserves_existing_pvc_request(tmp_path, configured, expected):
    (tmp_path / "values.yaml").write_text("persistence:\n  storageSize: 40Gi\n", encoding="utf-8")
    source = (Path(__file__).parents[2] / "install.sh").read_text(encoding="utf-8")
    start = source.index('if [[ -z "${PERSISTENCE_STORAGE_SIZE:-}" ]]; then')
    end = source.index('\nfi', start) + len('\nfi')
    command = source[start:end] + '\nprintf "%s" "$PERSISTENCE_STORAGE_SIZE"'
    result = subprocess.run(["bash", "-c", command], env={
        **os.environ, "INFRA_APPS_DIR": str(tmp_path), "PERSISTENCE_STORAGE_SIZE": configured,
    }, capture_output=True, text=True, check=True)
    assert result.stdout == expected


def test_source_chart_has_one_scheduled_pvc_writer_and_local_scratch():
    if not shutil.which("helm"):
        pytest.skip("Helm is required for the source chart contract")
    chart = Path(__file__).parents[2] / "k8s"
    result = subprocess.run(["helm", "template", str(chart)], capture_output=True, text=True, check=True)
    cronjobs = [item for item in yaml.safe_load_all(result.stdout) if item and item["kind"] == "CronJob"]
    pvc_writers = []
    for cronjob in cronjobs:
        pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        pvc = any("persistentVolumeClaim" in volume for volume in pod.get("volumes", []))
        if pvc and not cronjob["spec"].get("suspend", False):
            pvc_writers.append(cronjob["metadata"]["name"])
        if pvc:
            container = pod["containers"][0]
            assert {item["name"]: item.get("value") for item in container["env"]}["STREAMING_SQLITE_DIR"] == "/scratch"
            assert next(volume for volume in pod["volumes"] if volume["name"] == "scratch")["emptyDir"]["sizeLimit"] == "3500Mi"
    assert pvc_writers == ["log-analyzer"]
    threshold_job = next(item for item in cronjobs if item['metadata']['name'].endswith('-thresholds'))
    command = threshold_job['spec']['jobTemplate']['spec']['template']['spec']['containers'][0]['command'][-1]
    assert 'calculate_peak_thresholds.py --weeks 12' in command
    regular_job = next(item for item in cronjobs if item['metadata']['name'] == 'log-analyzer')
    regular_pod = regular_job['spec']['jobTemplate']['spec']['template']['spec']
    assert '--scheduled' in regular_pod['containers'][0]['command']
    assert regular_job['spec']['schedule'] == '5,20,35,50 * * * *'
    reporter = next(item for item in cronjobs if item['metadata']['name'].endswith('-reports'))
    assert reporter['spec']['schedule'] == '10 */2 * * *'
    report_pod = reporter['spec']['jobTemplate']['spec']['template']['spec']
    assert all('persistentVolumeClaim' not in volume for volume in report_pod['volumes'])
    assert report_pod['containers'][0]['command'] == ['python3', '/app/scripts/report_from_facts.py']
    report_env = {item['name'] for item in report_pod['containers'][0]['env']}
    assert not {'ES_USER', 'ES_PASSWORD', 'DB_DDL_USER', 'DB_DDL_PASSWORD', 'REGISTRY_DIR'} & report_env