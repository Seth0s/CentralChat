#!/usr/bin/env bash
# D1.2/D1.3 — Helm chart smoke (template + optional kind).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHART="$ROOT/deploy/helm/centralchat"
OUT="/tmp/centralchat-helm-render.yaml"

echo "[helm] Rendering chart..."
HELM_BIN=""
if command -v helm >/dev/null 2>&1; then
  HELM_BIN=helm
elif [ -x /tmp/helm-linux-amd64/helm ]; then
  HELM_BIN=/tmp/helm-linux-amd64/helm
else
  echo "[helm] Downloading helm binary to /tmp..."
  curl -fsSL https://get.helm.sh/helm-v3.14.4-linux-amd64.tar.gz | tar xz -C /tmp
  HELM_BIN=/tmp/linux-amd64/helm
fi
"$HELM_BIN" template centralchat-staging "$CHART" \
  -f "$CHART/values.yaml" \
  --namespace centralchat-staging \
  > "$OUT"
lines=$(wc -l < "$OUT")
echo "[helm] OK — $lines lines → $OUT"

if command -v kubectl >/dev/null 2>&1; then
  echo "[helm] kubectl dry-run client..."
  kubectl apply --dry-run=client -f "$OUT" >/dev/null
  echo "[helm] kubectl dry-run OK"
else
  echo "[helm] kubectl not installed — skipped dry-run (render-only)"
fi

if command -v kind >/dev/null 2>&1 && command -v helm >/dev/null 2>&1; then
  CLUSTER="${KIND_CLUSTER_NAME:-centralchat-helm}"
  if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
    echo "[helm] Creating kind cluster $CLUSTER..."
    kind create cluster --name "$CLUSTER"
  fi
  echo "[helm] helm upgrade --install on kind..."
  helm upgrade --install centralchat "$CHART" \
    --namespace centralchat-staging --create-namespace \
    -f "$CHART/values.yaml" \
    --set image.repository=centralchat/orchestrator \
    --set image.tag=latest \
    --kube-context "kind-$CLUSTER" \
    --dry-run
  echo "[helm] kind dry-run install OK"
else
  echo "[helm] kind/helm local not installed — use: kind create cluster && helm upgrade --install ..."
  echo "[helm] Rendered manifest is valid for manual review."
fi
