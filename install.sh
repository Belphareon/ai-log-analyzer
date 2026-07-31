#!/bin/bash
# =============================================================================
# AI Log Analyzer — INSTALL SCRIPT
# =============================================================================
# Připraví kompletní deployment v novém prod/nprod prostředí:
#   1. Načte profil prostředí a validuje konfiguraci
#   2. Vytvoří novou branch v příslušném infra-apps repozitáři
#   3. Vytvoří infra-apps/ai-log-analyzer.yaml (ArgoCD Application)
#   4. Vytvoří infra-apps/ai-log-analyzer/ (Helm chart + values)
#   5. Ověří YAML a Helm chart
#   6. Commitne a pushne branch pro PR
#
# Použití:
#   cp config/install.conf.example .env
#   ./install.sh
#   ./install.sh --dry-run
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Barvy ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}ℹ${NC}  $*"; }
ok()    { echo -e "${GREEN}✅${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠️${NC}  $*"; }
err()   { echo -e "${RED}❌${NC} $*"; }
header(){ echo ""; echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"; echo -e "${BLUE}  $*${NC}"; echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"; }

CHECKLIST=()
check_ok()   { CHECKLIST+=("✅ $*"); }
check_fail() { CHECKLIST+=("❌ $*"); }
check_skip() { CHECKLIST+=("⏭️  $*"); }

# ─── Argumenty ───────────────────────────────────────────────────────────────
DRY_RUN=false
CONFIG_FILE="$SCRIPT_DIR/.env"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --config)
            [[ $# -ge 2 ]] || { err "--config vyžaduje cestu k souboru"; exit 1; }
            CONFIG_FILE="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--dry-run] [--config FILE]"
            echo "  --dry-run      Vygeneruje a ověří výstup jen v dočasném adresáři"
            echo "  --config FILE  Použije jiný konfigurační soubor než .env"
            exit 0 ;;
        *) err "Neznámý argument: $1"; exit 1 ;;
    esac
done

# ─── Načtení konfigurace ─────────────────────────────────────────────────────
if [[ ! -f "$CONFIG_FILE" ]]; then
    err "Konfigurační soubor nenalezen: $CONFIG_FILE"
    echo "  Vytvoř ho: cp config/install.conf.example .env"
    echo "  Vyplň hodnoty a spusť znovu."
    exit 1
fi

set -a; source "$CONFIG_FILE"; set +a

case "${ENVIRONMENT:-}" in
    prod) ENV_PREFIX="PROD" ;;
    nprod) ENV_PREFIX="NPROD" ;;
    *) err "ENVIRONMENT musí být prod nebo nprod (aktuálně: ${ENVIRONMENT:-nenastaveno})"; exit 1 ;;
esac

use_environment_value() {
    local target_name="$1"
    local profile_name="${ENV_PREFIX}_${target_name}"
    printf -v "$target_name" '%s' "${!profile_name:-}"
}

for profile_value in \
    INFRA_APPS_REPO INFRA_APPS_BASE_BRANCH DB_HOST DB_NAME \
    DB_DDL_USER_D1 DB_DDL_USER_D2 DB_USER_D1 DB_USER_D2 \
    ES_HOST ES_INDEX CONJUR_LOB_USER CONJUR_SAFE_NAME \
    CONJUR_ACCOUNT_ES CONJUR_ACCOUNT_CONFLUENCE \
    CONFLUENCE_KNOWN_ERRORS_PAGE_ID CONFLUENCE_KNOWN_PEAKS_PAGE_ID \
    CONFLUENCE_RECENT_INCIDENTS_PAGE_ID SMTP_HOST EMAIL_FROM TEAMS_EMAIL
do
    use_environment_value "$profile_value"
done

DB_PORT="${DB_PORT:-5432}"
DB_DDL_ROLE="${DB_DDL_ROLE:-role_ailog_analyzer_ddl}"
DB_APP_ROLE="${DB_APP_ROLE:-role_ailog_analyzer_app}"
readonly DOCKER_IMAGE="dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:latest"
BRANCH_NAME="${BRANCH_NAME:-feat/ai-log-analyzer-${ENVIRONMENT}}"
INFRA_APPS_DIR="${INFRA_APPS_REPO}/infra-apps"
CHART_DIR="$INFRA_APPS_DIR/ai-log-analyzer"
APP_MANIFEST="$INFRA_APPS_DIR/ai-log-analyzer.yaml"

header "AI Log Analyzer — Instalace ($ENVIRONMENT)"
if $DRY_RUN; then warn "DRY-RUN mód — žádné změny nebudou provedeny"; fi

# ─── 1. Validace ─────────────────────────────────────────────────────────────
header "1/6  Validace konfigurace"

ERRORS=0
validate() {
    local var_name="$1" var_value="${!1:-}"
    if [[ -z "$var_value" || "$var_value" == "<"* ]]; then
        err "  $var_name není vyplněn"
        ((ERRORS++))
    else
        ok "  $var_name = $var_value"
    fi
}

validate_quiet() {
    local var_name="$1" var_value="${!1:-}"
    if [[ -z "$var_value" || "$var_value" == "<"* ]]; then
        err "  $var_name není vyplněn"
        ((ERRORS++))
    else
        ok "  $var_name je vyplněn"
    fi
}

validate_optional_url() {
    local var_name="$1" var_value="${!1:-}"
    if [[ -n "$var_value" && "$var_value" == "<"* ]]; then
        err "  $var_name obsahuje placeholder"
        ((ERRORS++))
    fi
}

validate_at_least_one() {
    # Vyžaduje, aby alespoň jedna z proměnných byla vyplněná (bez placeholderu)
    local names=("$@") found=false
    for n in "${names[@]}"; do
        local v="${!n:-}"
        if [[ -n "$v" && "$v" != "<"* ]]; then
            found=true
            ok "  $n = $v"
        fi
    done
    if [[ "$found" == false ]]; then
        err "  Alespoň jedno z: ${names[*]} musí být vyplněno (webhook a/nebo email kanál)"
        ((ERRORS++))
    fi
}

# Povinné
validate ENVIRONMENT
validate DOCKER_IMAGE
validate INFRA_APPS_REPO
validate INFRA_APPS_BASE_BRANCH
validate DB_HOST
validate DB_PORT
validate DB_NAME
validate DB_DDL_USER_D1
validate DB_DDL_USER_D2
validate DB_USER_D1
validate DB_USER_D2
validate ES_HOST
validate ES_INDEX
validate CONFLUENCE_URL
validate CONFLUENCE_KNOWN_ERRORS_PAGE_ID
validate CONFLUENCE_KNOWN_PEAKS_PAGE_ID
validate CONFLUENCE_RECENT_INCIDENTS_PAGE_ID
validate_optional_url TEAMS_WEBHOOK_URL
validate_at_least_one TEAMS_WEBHOOK_URL TEAMS_EMAIL
validate SMTP_HOST
validate SMTP_PORT
validate EMAIL_FROM
validate CONJUR_APP_ID
validate CONJUR_LOB_USER
validate CONJUR_SAFE_NAME
validate CONJUR_ACCOUNT_ES
validate CONJUR_ACCOUNT_CONFLUENCE
validate MONITORED_NAMESPACES

if [[ $ERRORS -gt 0 ]]; then
    err "$ERRORS proměnných není vyplněno. Uprav .env a spusť znovu."
    exit 1
fi

ok "Validace OK ($ENVIRONMENT)"
check_ok "Konfigurace validována"

# ─── 2. Příprava infra-apps branche ─────────────────────────────────────────
header "2/6  Infra-apps branch"

if [[ ! -d "$INFRA_APPS_REPO/.git" ]]; then
    err "INFRA_APPS_REPO není Git repozitář: $INFRA_APPS_REPO"
    exit 1
fi

info "V infra-apps vznikne nová branch: $BRANCH_NAME"
info "Vytvoří se kompletní struktura:"
info "  infra-apps/ai-log-analyzer.yaml"
info "  infra-apps/ai-log-analyzer/"

if $DRY_RUN; then
    WORK_DIR="$(mktemp -d)"
    trap 'rm -rf "$WORK_DIR"' EXIT
    INFRA_APPS_DIR="$WORK_DIR/infra-apps"
    CHART_DIR="$INFRA_APPS_DIR/ai-log-analyzer"
    APP_MANIFEST="$INFRA_APPS_DIR/ai-log-analyzer.yaml"
    mkdir -p "$INFRA_APPS_DIR"
    check_skip "Git branch (dry-run)"
else
    cd "$INFRA_APPS_REPO"
    git diff --quiet && git diff --cached --quiet || {
        err "Infra-apps repozitář obsahuje necommitnuté změny. Před instalací je ukliď."
        exit 1
    }
    git show-ref --verify --quiet "refs/heads/$BRANCH_NAME" && {
        err "Lokální branch už existuje: $BRANCH_NAME"
        exit 1
    }
    git ls-remote --exit-code --heads origin "$BRANCH_NAME" > /dev/null 2>&1 && {
        err "Vzdálená branch už existuje: $BRANCH_NAME"
        exit 1
    }
    git switch "$INFRA_APPS_BASE_BRANCH"
    git pull --ff-only origin "$INFRA_APPS_BASE_BRANCH"
    git switch -c "$BRANCH_NAME"
    mkdir -p "$INFRA_APPS_DIR"
    ok "Branch vytvořena: $BRANCH_NAME"
    check_ok "Git branch: $BRANCH_NAME"
fi

# ─── 3. Kompletní infra-apps struktura ───────────────────────────────────────
header "3/6  K8s struktura"

mkdir -p "$CHART_DIR/templates"
cp "$SCRIPT_DIR/k8s/Chart.yaml" "$CHART_DIR/Chart.yaml"
cp "$SCRIPT_DIR/k8s/README.md" "$CHART_DIR/README.md"
cp -R "$SCRIPT_DIR/k8s/templates/." "$CHART_DIR/templates/"

REPO_URL="$(git -C "$INFRA_APPS_REPO" remote get-url origin | sed -E 's#https://[^/@]+@#https://#')"

cat > "$APP_MANIFEST" << APPEOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ai-log-analyzer
  namespace: argocd-system
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: ai-log-analyzer
    server: "https://kubernetes.default.svc"
  source:
    path: infra-apps/ai-log-analyzer
    repoURL: "$REPO_URL"
    targetRevision: "$INFRA_APPS_BASE_BRANCH"
  project: application
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
    automated:
      prune: true
      selfHeal: true
APPEOF

info "Generuji values.yaml pro $ENVIRONMENT..."
PROXY_VALUE="${CONFLUENCE_PROXY:-http://cntlm.speed-default:3128}"

cat > "$CHART_DIR/values.yaml" << VALEOF
# =============================================================================
# AI Log Analyzer — values.yaml ($ENVIRONMENT)
# =============================================================================
# Generováno: $(date '+%Y-%m-%d %H:%M:%S') pomocí install.sh
# Zdroj hodnot: ${ENV_PREFIX}_* profil v $(basename "$CONFIG_FILE")
# =============================================================================

# -----------------------------------------------------------------------------
# Základní identita aplikace
# -----------------------------------------------------------------------------
namespace: ai-log-analyzer
environment: $ENVIRONMENT

app:
  name: log-analyzer
  # Image se vždy používá z aplikačního repozitáře. Instalační balíček ji nebuildí.
  image: "$DOCKER_IMAGE"
  imagePullPolicy: IfNotPresent
  secretName: log-analyzer-secrets

# -----------------------------------------------------------------------------
# Výpočetní prostředky
# -----------------------------------------------------------------------------
resources:
  requests:
    cpu: 500m
    memory: 1Gi
  limits:
    cpu: "2"
    memory: 4Gi

persistence:
  enabled: true
  claimName: log-analyzer-data
  mountPath: /data
  subPaths:
    registry: registry
    exports: exports
    reports: reports

# -----------------------------------------------------------------------------
# CyberArk / Conjur
# Hesla se sem nezapisují. Uvádějí se názvy účtů obdržené při založení DB.
# D1 se nyní používá pro runtime a migrace; D2 je uložen pro budoucí přepínání.
# -----------------------------------------------------------------------------
conjur:
  applicationId: $CONJUR_APP_ID
  componentId: restricted
  lobUser: $CONJUR_LOB_USER
  safeName: $CONJUR_SAFE_NAME
  accounts:
    confluence: $CONJUR_ACCOUNT_CONFLUENCE
    elastic: $CONJUR_ACCOUNT_ES
    database:
      d1: $DB_USER_D1
      d2: $DB_USER_D2
    database_ddl:
      d1: $DB_DDL_USER_D1
      d2: $DB_DDL_USER_D2

# -----------------------------------------------------------------------------
# Runtime konfigurace
# -----------------------------------------------------------------------------
env:
  # Obecné
  ENVIRONMENT: $ENVIRONMENT
  LOG_LEVEL: ${LOG_LEVEL:-INFO}
  REGISTRY_DIR: /data/registry
  EXPORT_DIR: /data/exports

  # PostgreSQL spojení z JDBC údajů. Hesla dodává Conjur.
  DB_HOST: "$DB_HOST"
  DB_NAME: "$DB_NAME"
  DB_PORT: "$DB_PORT"
  # DB_DDL_ROLE: oprávnění pro tvorbu a změny schématu během init/migrací.
  DB_DDL_ROLE: "$DB_DDL_ROLE"
  # DB_APP_ROLE: oprávnění běžící aplikace pro čtení a zápis dat.
  DB_APP_ROLE: "$DB_APP_ROLE"

  # Elasticsearch
  ES_HOST: "$ES_HOST"
  ES_INDEX: "$ES_INDEX"

  # Confluence a proxy
  CONFLUENCE_URL: "$CONFLUENCE_URL"
  CONFLUENCE_PROXY: "$PROXY_VALUE"
  HTTP_PROXY: "$PROXY_VALUE"
  HTTPS_PROXY: "$PROXY_VALUE"
  CONFLUENCE_KNOWN_ERRORS_PAGE_ID: "$CONFLUENCE_KNOWN_ERRORS_PAGE_ID"
  CONFLUENCE_KNOWN_PEAKS_PAGE_ID: "$CONFLUENCE_KNOWN_PEAKS_PAGE_ID"
  CONFLUENCE_RECENT_INCIDENTS_PAGE_ID: "$CONFLUENCE_RECENT_INCIDENTS_PAGE_ID"

  # Detekce peaků a alerting
  SPIKE_THRESHOLD: "${SPIKE_THRESHOLD:-3.0}"
  EWMA_ALPHA: "${EWMA_ALPHA:-0.3}"
  WINDOW_MINUTES: "${WINDOW_MINUTES:-15}"
  PERCENTILE_LEVEL: "${PERCENTILE_LEVEL:-0.93}"
  MIN_SAMPLES_FOR_THRESHOLD: "${MIN_SAMPLES_FOR_THRESHOLD:-10}"
  DEFAULT_THRESHOLD: "${DEFAULT_THRESHOLD:-100}"
  MAX_PEAK_ALERTS_PER_WINDOW: "${MAX_PEAK_ALERTS_PER_WINDOW:-3}"
  ALERT_DIGEST_ENABLED: "${ALERT_DIGEST_ENABLED:-true}"
  ALERT_COOLDOWN_MIN: "${ALERT_COOLDOWN_MIN:-45}"
  ALERT_HEARTBEAT_MIN: "${ALERT_HEARTBEAT_MIN:-120}"
  ALERT_MIN_DELTA_PCT: "${ALERT_MIN_DELTA_PCT:-30}"
  ALERT_CONTINUATION_LOOKBACK_MIN: "${ALERT_CONTINUATION_LOOKBACK_MIN:-60}"

init:
  backfillDays: ${INIT_BACKFILL_DAYS:-21}
  backfillWorkers: ${INIT_BACKFILL_WORKERS:-4}
  thresholdWeeks: ${INIT_THRESHOLD_WEEKS:-3}
  activeDeadlineSeconds: 14400

email:
  smtpHost: "$SMTP_HOST"
  smtpPort: "${SMTP_PORT:-25}"
  from: "$EMAIL_FROM"

teams:
  enabled: "${TEAMS_ENABLED:-false}"
  webhook_url: "${TEAMS_WEBHOOK_URL:-}"
  email: "$TEAMS_EMAIL"
VALEOF

ok "Vytvořen ArgoCD manifest i kompletní Helm chart"
check_ok "K8s struktura: infra-apps/ai-log-analyzer{.yaml,/}"

# ─── 4. Validace výstupu ─────────────────────────────────────────────────────
header "4/6  Validace výstupu"

python3 - "$APP_MANIFEST" "$CHART_DIR/values.yaml" <<'PYEOF'
import sys
import yaml

for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise SystemExit(f"Neplatný YAML objekt: {path}")
print("YAML parse OK")
PYEOF

if command -v helm > /dev/null 2>&1; then
    helm lint "$CHART_DIR"
    helm template ai-log-analyzer "$CHART_DIR" > /dev/null
    ok "Helm lint a render OK"
else
    warn "Helm není nainstalován; proběhla pouze YAML validace"
fi
check_ok "YAML/Helm validace"

# ─── 5. Commit a push ────────────────────────────────────────────────────────
header "5/6  Git commit & push"

if $DRY_RUN; then
    info "DRY-RUN: výstup byl úspěšně vygenerován a ověřen v dočasném adresáři"
    check_skip "Git commit/push (dry-run)"
else
    cd "$INFRA_APPS_REPO"
    git add "infra-apps/ai-log-analyzer.yaml" "infra-apps/ai-log-analyzer/"
    git commit -m "feat: install ai-log-analyzer in $ENVIRONMENT"
    git push -u origin "$BRANCH_NAME"
    ok "Branch pushnuta: $BRANCH_NAME"
    check_ok "Git commit a push"
fi

# ─── 6. Souhrn & další kroky ─────────────────────────────────────────────────
header "6/6  SOUHRN"

echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│  DEPLOYMENT CHECKLIST                                   │"
echo "├─────────────────────────────────────────────────────────┤"
for item in "${CHECKLIST[@]}"; do
    printf "│  %-55s │\n" "$item"
done
echo "└─────────────────────────────────────────────────────────┘"

echo ""
echo -e "${BLUE}══════════  DALŠÍ KROKY  ═══════════════════════════════════${NC}"
echo ""
echo "  1. VYTVOŘIT PR z branch: $BRANCH_NAME"
echo "     → Zkontroluj: infra-apps/ai-log-analyzer.yaml"
echo "     → Zkontroluj: infra-apps/ai-log-analyzer/values.yaml"
echo ""
echo "  2. MERGE PR → ArgoCD automaticky nasadí"
echo ""
echo "  3. OVĚŘIT v ArgoCD, že je vše Synced & Healthy:"
echo "     kubectl get all -n ai-log-analyzer"
echo ""
echo "  4. SPUSTIT INIT JOB (jednorázový bootstrap):"
echo "     kubectl create job log-analyzer-init-manual \\"
echo "       --from=cronjob/log-analyzer -n ai-log-analyzer \\"
echo "       -- /bin/bash -c 'python3 /app/scripts/backfill.py --days ${INIT_BACKFILL_DAYS:-21} --force && python3 /app/scripts/core/calculate_peak_thresholds.py --weeks ${INIT_THRESHOLD_WEEKS:-3}'"
echo "     NEBO pokud je init Job template v manifestech:"
echo "     helm template $CHART_DIR | kubectl apply -f - -l job-type=init"
echo ""
echo "  5. SLEDOVAT init job:"
echo "     kubectl logs -f job/log-analyzer-init -n ai-log-analyzer"
echo ""
echo "  6. OVĚŘIT po init jobu:"
echo "     kubectl create job verify-check --from=cronjob/log-analyzer-thresholds -n ai-log-analyzer"
echo "     kubectl logs -f job/verify-check -n ai-log-analyzer"
echo ""
echo "  7. OVĚŘIT CronJoby běží:"
echo "     kubectl get cronjobs -n ai-log-analyzer"
echo "     kubectl get jobs -n ai-log-analyzer --sort-by=.metadata.creationTimestamp"
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Instalace dokončena. Pokračuj kroky výše.${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
