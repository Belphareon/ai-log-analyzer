from pathlib import Path

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
    assert values["email"]["smtpHost"] == "${SMTP_HOST:-css-smtp-prod-os.sos.kb.cz}"
    assert values["teams"]["enabled"] == "${TEAMS_ENABLED:-false}"