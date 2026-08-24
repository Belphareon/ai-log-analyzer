#!/bin/bash
# =============================================================================
# AI Log Analyzer — INSTALL SCRIPT
# =============================================================================
# Orchestruje celou instalaci po splnění prerekvizit:
#   1. Validace .env konfigurace
#   2. DB schéma — migrace + oprávnění
#   3. Docker build & push
#   4. Generování values.yaml + kopírování manifestů do infra-apps repo
#   5. Commit & push (nová branch pro PR)
#   6. Výpis dalších kroků (init joby po ArgoCD sync)
#
# Použití:
#   cp .env.example .env   # vyplnit hodnoty
#   ./install.sh            # spustit instalaci
#   ./install.sh --dry-run  # bez DB/Docker/git změn; chart se přegeneruje
#   ./install.sh --run-db-migrations  # volitelně spustit DB migrace lokálně
#   ./install.sh --skip-docker  # přeskočit Docker build
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
SKIP_DB=true
SKIP_DOCKER=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)     DRY_RUN=true;     shift ;;
        --skip-db)     SKIP_DB=true;     shift ;;
        --run-db-migrations) SKIP_DB=false; shift ;;
        --skip-docker) SKIP_DOCKER=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--dry-run] [--run-db-migrations] [--skip-db] [--skip-docker]"
            echo "  --dry-run      Přeskočí DB migrace, Docker a git; přegeneruje chart v INFRA_APPS_DIR"
            echo "  --run-db-migrations  Spustit DB migrace lokálně pomocí DB_DDL_* z .env"
            echo "  --skip-db      Přeskočit lokální DB migrace (default; migrace běží v K8s init jobu přes Conjur)"
            echo "  --skip-docker  Přeskočit Docker build & push"
            exit 0 ;;
        *) err "Neznámý argument: $1"; exit 1 ;;
    esac
done

# ─── Load .env ───────────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
    err ".env soubor nenalezen!"
    echo "  Vytvoř ho:  cp .env.example .env"
    echo "  Vyplň hodnoty a spusť znovu."
    exit 1
fi

set -a; source .env; set +a

case "${ENVIRONMENT:-}" in
    prod) PROFILE_PREFIX=PROD ;;
    nprod) PROFILE_PREFIX=NPROD ;;
    *)
        err "ENVIRONMENT musí být prod nebo nprod"
        exit 1
        ;;
esac

use_profile_value() {
    local variable_name="$1"
    local profile_variable="${PROFILE_PREFIX}_${variable_name}"
    local profile_value="${!profile_variable:-}"

    if [[ -n "$profile_value" ]]; then
        printf -v "$variable_name" '%s' "$profile_value"
        export "$variable_name"
    fi
}

for variable_name in \
    DB_HOST DB_NAME DB_DDL_USER_D1 DB_DDL_USER_D2 DB_USER_D1 DB_USER_D2 \
    DB_DDL_ROLE DB_APP_ROLE ES_HOST ES_INDEX MONITORED_NAMESPACES \
    CONJUR_LOB_USER CONJUR_SAFE_NAME \
    CONJUR_ACCOUNT_DB CONJUR_ACCOUNT_DB_DDL \
    CONJUR_ACCOUNT_ES CONJUR_ACCOUNT_CONFLUENCE \
    CONFLUENCE_KNOWN_ERRORS_PAGE_ID CONFLUENCE_KNOWN_PEAKS_PAGE_ID \
    CONFLUENCE_RECENT_INCIDENTS_PAGE_ID SMTP_HOST EMAIL_FROM TEAMS_EMAIL
do
    use_profile_value "$variable_name"
done

INFRA_APPS_DIR="${INFRA_APPS_DIR:-${PROFILE_PREFIX}_INFRA_APPS_REPO}"
if [[ "$INFRA_APPS_DIR" == "${PROFILE_PREFIX}_INFRA_APPS_REPO" ]]; then
    INFRA_APPS_DIR="${!INFRA_APPS_DIR}/infra-apps/ai-log-analyzer"
fi
CONJUR_ACCOUNT_DB="${CONJUR_ACCOUNT_DB:-${DB_USER_D1:-}}"
CONJUR_ACCOUNT_DB_DDL="${CONJUR_ACCOUNT_DB_DDL:-${DB_DDL_USER_D1:-}}"

header "AI Log Analyzer — Instalace ($ENVIRONMENT)"
if $DRY_RUN; then warn "DRY-RUN mód — DB, Docker a git se nemění; chart se přegeneruje"; fi

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
validate DOCKER_SQUAD
validate IMAGE_TAG
validate INFRA_APPS_DIR
validate DB_HOST
validate DB_PORT
validate DB_NAME
validate DB_DDL_ROLE
validate DB_APP_ROLE
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
validate CONJUR_ACCOUNT_DB
validate CONJUR_ACCOUNT_DB_DDL
validate CONJUR_ACCOUNT_ES
validate CONJUR_ACCOUNT_CONFLUENCE
validate MONITORED_NAMESPACES

if ! $SKIP_DB; then
    validate DB_USER
    validate DB_PASSWORD
    validate DB_DDL_USER
    validate DB_DDL_PASSWORD
fi

if [[ $ERRORS -gt 0 ]]; then
    err "$ERRORS proměnných není vyplněno. Uprav .env a spusť znovu."
    exit 1
fi

# Odvozené proměnné
DOCKER_IMAGE="${DOCKER_REGISTRY:-dockerhub.kb.cz}/${DOCKER_SQUAD}/ai-log-analyzer:${IMAGE_TAG}"
ANALYZER_REPO_DIR="${ANALYZER_REPO_DIR:-$SCRIPT_DIR}"

ok "Validace OK ($ENVIRONMENT)"
check_ok "Konfigurace validována"

# ─── 2. DB Schéma ────────────────────────────────────────────────────────────
header "2/6  Databáze — migrace schématu"

if $SKIP_DB; then
    warn "Lokální DB migrace přeskočeny (default)"
    info "Prod/NPROD migrace poběží v K8s init jobu přes CyberArk/Conjur a DB_DDL_* secret."
    check_skip "DB migrace (K8s init job přes Conjur)"
else
    info "Host: $DB_HOST:$DB_PORT / $DB_NAME"
    info "DDL user: $DB_DDL_USER"

    # Test připojení
    if ! PGPASSWORD="$DB_DDL_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_DDL_USER" -d "$DB_NAME" -c "SELECT 1;" > /dev/null 2>&1; then
        err "Nelze se připojit k DB jako $DB_DDL_USER"
        err "Ověř, že DB existuje a DDL user má přístup."
        exit 1
    fi
    ok "DB připojení OK"

    if $DRY_RUN; then
        info "DRY-RUN: Migrace by se spustily:"
        for f in scripts/migrations/[0-9]*.sql; do
            info "  → $f"
        done
        check_skip "DB migrace (dry-run)"
    else
        info "Spouštím migrace..."
        for f in scripts/migrations/[0-9]*.sql; do
            info "  → $(basename "$f")"
            PGPASSWORD="$DB_DDL_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" \
                -U "$DB_DDL_USER" -d "$DB_NAME" -f "$f" 2>&1 || {
                warn "  Migrace $(basename "$f") vrátila warning (může být OK pokud tabulka existuje)"
            }
        done
        ok "Migrace dokončeny"

        # Oprávnění pro app roli
        info "Nastavuji oprávnění pro app roli..."
        PGPASSWORD="$DB_DDL_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" \
            -U "$DB_DDL_USER" -d "$DB_NAME" -c "
            SET ROLE ${DB_DDL_ROLE};
            GRANT USAGE ON SCHEMA ailog_peak TO ${DB_APP_ROLE};
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ailog_peak TO ${DB_APP_ROLE};
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ailog_peak TO ${DB_APP_ROLE};
        " 2>&1 || warn "GRANT příkazy vrátily warning"
        ok "Oprávnění nastavena"

        # Ověření
        TABLE_COUNT=$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" \
            -U "$DB_USER" -d "$DB_NAME" -tAc \
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='ailog_peak';")
        if [[ "$TABLE_COUNT" -ge 4 ]]; then
            ok "DB ověření: $TABLE_COUNT tabulek v ailog_peak"
            check_ok "DB migrace ($TABLE_COUNT tabulek)"
        else
            err "DB ověření: jen $TABLE_COUNT tabulek (očekáváno ≥4)"
            check_fail "DB migrace (jen $TABLE_COUNT tabulek)"
        fi
    fi
fi

# ─── 3. Docker Build & Push ──────────────────────────────────────────────────
header "3/6  Docker build & push"

if $SKIP_DOCKER; then
    warn "Přeskočeno (--skip-docker)"
    check_skip "Docker build (přeskočeno)"
else
    info "Image: $DOCKER_IMAGE"

    if $DRY_RUN; then
        info "DRY-RUN: docker build -t $DOCKER_IMAGE ."
        info "DRY-RUN: docker push $DOCKER_IMAGE"
        check_skip "Docker build (dry-run)"
    else
        info "Building..."
        docker build -t "$DOCKER_IMAGE" "$ANALYZER_REPO_DIR"
        ok "Build OK"

        info "Pushing..."
        docker push "$DOCKER_IMAGE"
        ok "Push OK: $DOCKER_IMAGE"
        check_ok "Docker image: $DOCKER_IMAGE"
    fi
fi

# ─── 4. Generování values.yaml + kopírování do infra-apps ────────────────────
header "4/6  K8s manifesty → infra-apps repozitář"

if [[ ! -d "$INFRA_APPS_DIR" ]]; then
    err "Infra-apps adresář neexistuje: $INFRA_APPS_DIR"
    err "Naklonuj příslušný k8s-infra-apps-<env> repozitář."
    exit 1
fi

# Generování values.yaml z .env
info "Generuji values.yaml pro $ENVIRONMENT..."
PROXY_VALUE="${CONFLUENCE_PROXY:-http://cntlm.speed-default:3128}"

cat > "$INFRA_APPS_DIR/values.yaml" << VALEOF
# =============================================================================
# AI Log Analyzer — values.yaml ($ENVIRONMENT)
# =============================================================================
# Generováno: $(date '+%Y-%m-%d %H:%M:%S') pomocí install.sh
# ZKONTROLUJ a dolad, pokud je třeba!
# =============================================================================

namespace: ai-log-analyzer
environment: $ENVIRONMENT

app:
  name: log-analyzer
  image: $DOCKER_IMAGE
  imagePullPolicy: IfNotPresent
  secretName: log-analyzer-secrets

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

conjur:
  image: dockerhub.kb.cz/ps-sq008-pub/cyberark/secrets-provider-for-k8s:1.7.3-kb.1
  imagePullPolicy: IfNotPresent
  containerName: conjur-secrets-provider
  applicationId: $CONJUR_APP_ID
  componentId: restricted
  lobUser: $CONJUR_LOB_USER
  safeName: $CONJUR_SAFE_NAME
  accounts:
    confluence: $CONJUR_ACCOUNT_CONFLUENCE
    database: $CONJUR_ACCOUNT_DB
    database_ddl: $CONJUR_ACCOUNT_DB_DDL
    elastic: $CONJUR_ACCOUNT_ES

env:
  ENVIRONMENT: $ENVIRONMENT
  LOG_LEVEL: ${LOG_LEVEL:-INFO}
  REGISTRY_DIR: /data/registry
  EXPORT_DIR: /data/exports
  DB_HOST: "$DB_HOST"
  DB_NAME: "$DB_NAME"
  DB_PORT: "$DB_PORT"
  DB_DDL_ROLE: "$DB_DDL_ROLE"
  DB_APP_ROLE: "$DB_APP_ROLE"
  ES_HOST: "$ES_HOST"
  ES_INDEX: "$ES_INDEX"
  MONITORED_NAMESPACES: "$MONITORED_NAMESPACES"
  CONFLUENCE_URL: "$CONFLUENCE_URL"
  CONFLUENCE_PROXY: "$PROXY_VALUE"
  HTTP_PROXY: "$PROXY_VALUE"
  HTTPS_PROXY: "$PROXY_VALUE"
  CONFLUENCE_KNOWN_ERRORS_PAGE_ID: "$CONFLUENCE_KNOWN_ERRORS_PAGE_ID"
  CONFLUENCE_KNOWN_PEAKS_PAGE_ID: "$CONFLUENCE_KNOWN_PEAKS_PAGE_ID"
  CONFLUENCE_RECENT_INCIDENTS_PAGE_ID: "$CONFLUENCE_RECENT_INCIDENTS_PAGE_ID"
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
  FACT_RETENTION_DAYS: "${FACT_RETENTION_DAYS:-90}"

init:
  backfillDays: ${INIT_BACKFILL_DAYS:-21}
  backfillWorkers: ${INIT_BACKFILL_WORKERS:-4}
  thresholdWeeks: ${INIT_THRESHOLD_WEEKS:-3}
  activeDeadlineSeconds: 14400

email:
  smtpHost: "${SMTP_HOST:-css-smtp-prod-os.sos.kb.cz}"
  smtpPort: "${SMTP_PORT:-25}"
  from: "${EMAIL_FROM:-ai-log-analyzer@kb.cz}"

teams:
  enabled: "${TEAMS_ENABLED:-false}"
  webhook_url: "${TEAMS_WEBHOOK_URL:-}"
  email: "$TEAMS_EMAIL"
VALEOF

ok "values.yaml vygenerován"

# Kopie templates (pokud chybí)
if [[ ! -d "$INFRA_APPS_DIR/templates" ]]; then
    info "Kopíruji K8s templates..."
    cp -r "$ANALYZER_REPO_DIR/k8s/templates" "$INFRA_APPS_DIR/templates"
    ok "Templates zkopírovány"
fi

if [[ ! -f "$INFRA_APPS_DIR/Chart.yaml" ]]; then
    cp "$ANALYZER_REPO_DIR/k8s/Chart.yaml" "$INFRA_APPS_DIR/Chart.yaml"
    ok "Chart.yaml zkopírován"
fi

# Aktualizace templates (vždy přepsat)
info "Aktualizuji templates z aktuální verze..."
cp -r "$ANALYZER_REPO_DIR/k8s/templates/"* "$INFRA_APPS_DIR/templates/"
cp "$ANALYZER_REPO_DIR/k8s/Chart.yaml" "$INFRA_APPS_DIR/Chart.yaml"
ok "Templates aktualizovány"

check_ok "K8s manifesty v $INFRA_APPS_DIR"

# ─── 5. Commit & Push do nové branch ─────────────────────────────────────────
header "5/6  Git commit & push (infra-apps)"

BRANCH_NAME="feat/ai-log-analyzer-${ENVIRONMENT}-${IMAGE_TAG}"

if $DRY_RUN; then
    info "DRY-RUN: Vytvořila by se branch: $BRANCH_NAME"
    check_skip "Git commit (dry-run)"
else
    pushd "$INFRA_APPS_DIR/.." > /dev/null  # infra-apps/
    cd "$(git rev-parse --show-toplevel)"     # root of infra-apps repo

    info "Branch: $BRANCH_NAME"
    git checkout -b "$BRANCH_NAME" 2>/dev/null || git checkout "$BRANCH_NAME"
    git add "infra-apps/ai-log-analyzer/"
    git commit -m "feat: ai-log-analyzer $ENVIRONMENT $IMAGE_TAG

Generováno install.sh: $(date '+%Y-%m-%d %H:%M:%S')" || warn "Žádné změny k commitnutí"

    git push -u origin "$BRANCH_NAME" 2>&1 || {
        warn "Push selhal — proveď manuálně: git push -u origin $BRANCH_NAME"
    }
    ok "Branch $BRANCH_NAME pushed"
    popd > /dev/null
    check_ok "Git: $BRANCH_NAME pushed"
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
echo "     → Zkontroluj values.yaml v PR: $INFRA_APPS_DIR/values.yaml"
echo ""
echo "  2. MERGE PR → ArgoCD automaticky nasadí"
echo ""
echo "  3. OVĚŘIT v ArgoCD, že je vše Synced & Healthy:"
echo "     kubectl get all -n ai-log-analyzer"
echo ""
echo "  4. INIT JOB (jednorázový bootstrap):"
echo "     Init Job je součástí chartu a spustí se při ArgoCD syncu."
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
