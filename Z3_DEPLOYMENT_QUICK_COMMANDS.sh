#!/bin/bash
# Z3 Solver Service Deployment - Copy & Paste Commands
# Save as: z3-deploy.sh && bash z3-deploy.sh

set -e  # Exit on error

echo "======================================================================="
echo "DSG Z3 Solver Deployment - Path A (Real Z3 + Maximum Power)"
echo "======================================================================="
echo ""

# Configuration
PROJECT_ID="agi-dsg"
REGION="us-central1"
SERVICE_NAME="z3-solver-service"
ARTIFACT_REGISTRY_REPO="z3-solver-repo"
DOCKER_IMAGE_NAME="z3-solver-service"

# =========================================================================
# STEP 1: Generate Secret
# =========================================================================

echo "[STEP 1] Generating shared secret..."
SECRET=$(openssl rand -hex 32)
echo "Generated secret: $SECRET"
echo "SAVE THIS SECRET NOW (you'll need it for Render + Cloud Run)"
echo ""

# =========================================================================
# STEP 2: Build & Push Docker Image
# =========================================================================

echo "[STEP 2] Building Docker image..."
# Assumes you have z3-solver-service.py, Dockerfile, requirements.txt in current dir

if [ ! -f "z3-solver-service.py" ] || [ ! -f "Dockerfile" ] || [ ! -f "requirements.txt" ]; then
  echo "ERROR: Missing required files (z3-solver-service.py, Dockerfile, requirements.txt)"
  exit 1
fi

docker build -t $DOCKER_IMAGE_NAME:latest .
echo "✓ Docker image built"
echo ""

echo "[STEP 2.1] Testing Docker image locally..."
docker run -d \
  -e DSG_SOLVER_SHARED_SECRET="$SECRET" \
  -p 8080:8080 \
  --name test-z3 \
  $DOCKER_IMAGE_NAME:latest

# Wait for container to start
sleep 3

# Test health endpoint
if curl -s http://localhost:8080/health | grep -q "ok"; then
  echo "✓ Local Docker test passed"
else
  echo "✗ Local Docker test failed"
  docker logs test-z3
  docker stop test-z3
  docker rm test-z3
  exit 1
fi

docker stop test-z3
docker rm test-z3
echo ""

# =========================================================================
# STEP 3: Setup GCP & Artifact Registry
# =========================================================================

echo "[STEP 3] Setting up GCP project..."
gcloud config set project $PROJECT_ID
gcloud services enable artifactregistry.googleapis.com
echo "✓ Artifact Registry API enabled"
echo ""

echo "[STEP 3.1] Creating Artifact Registry repository..."
gcloud artifacts repositories create $ARTIFACT_REGISTRY_REPO \
  --location=$REGION \
  --repository-format=docker \
  --project=$PROJECT_ID 2>/dev/null || echo "Repository already exists"
echo "✓ Artifact Registry repository ready"
echo ""

echo "[STEP 3.2] Configuring Docker authentication..."
gcloud auth configure-docker $REGION-docker.pkg.dev
echo "✓ Docker auth configured"
echo ""

# =========================================================================
# STEP 4: Push Docker Image
# =========================================================================

echo "[STEP 4] Pushing Docker image to Artifact Registry..."
docker tag $DOCKER_IMAGE_NAME:latest \
  $REGION-docker.pkg.dev/$PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$DOCKER_IMAGE_NAME:latest

docker push $REGION-docker.pkg.dev/$PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$DOCKER_IMAGE_NAME:latest
echo "✓ Docker image pushed"
echo ""

# =========================================================================
# STEP 5: Deploy to Cloud Run
# =========================================================================

echo "[STEP 5] Deploying to Cloud Run..."
gcloud services enable run.googleapis.com

gcloud run deploy $SERVICE_NAME \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/$ARTIFACT_REGISTRY_REPO/$DOCKER_IMAGE_NAME:latest \
  --platform managed \
  --region $REGION \
  --project $PROJECT_ID \
  --set-env-vars="DSG_SOLVER_SHARED_SECRET=$SECRET" \
  --memory 2Gi \
  --timeout 120 \
  --max-instances 100 \
  --min-instances 0 \
  --ingress all \
  --allow-unauthenticated

echo "✓ Cloud Run deployment complete"
echo ""

# =========================================================================
# STEP 6: Get Service URL
# =========================================================================

echo "[STEP 6] Retrieving service URL..."
SERVICE_URL=$(gcloud run services list \
  --format='value(status.url)' \
  --filter="metadata.name:$SERVICE_NAME" \
  --region=$REGION \
  --project=$PROJECT_ID)

echo "✓ Service URL: $SERVICE_URL"
echo ""

# =========================================================================
# STEP 7: Test Cloud Run Service
# =========================================================================

echo "[STEP 7] Testing Cloud Run service..."

# Health check
echo "Testing health endpoint..."
if curl -s "$SERVICE_URL/health" | grep -q "ok"; then
  echo "✓ Health check passed"
else
  echo "✗ Health check failed"
  curl -v "$SERVICE_URL/health"
  exit 1
fi

# Info endpoint with auth
echo "Testing info endpoint with authentication..."
INFO_RESPONSE=$(curl -s \
  -H "Authorization: Bearer $SECRET" \
  "$SERVICE_URL/info")

if echo "$INFO_RESPONSE" | grep -q "z3_available"; then
  echo "✓ Info endpoint passed"
  echo "Response:"
  echo "$INFO_RESPONSE" | jq .
else
  echo "✗ Info endpoint failed"
  echo "$INFO_RESPONSE"
  exit 1
fi
echo ""

# =========================================================================
# STEP 8: Test QUBO Solver
# =========================================================================

echo "[STEP 8] Testing QUBO solver with AIMO test case..."
QUBO_RESPONSE=$(curl -s -X POST "$SERVICE_URL/api/solve/qubo" \
  -H "Authorization: Bearer $SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "schemaVersion": "dsg-aimo-exact-energy-v1",
    "problemId": "sealed-connectivity-smoke-v1",
    "problem": {},
    "problemHash": "",
    "encodingHash": "",
    "encoding": {
      "kind": "qubo-v1",
      "variableCount": 3,
      "linear": [
        {"i": 0, "weight": "-4"},
        {"i": 1, "weight": "-3"},
        {"i": 2, "weight": "1"}
      ],
      "quadratic": [
        {"i": 0, "j": 1, "weight": "5"},
        {"i": 1, "j": 2, "weight": "2"}
      ]
    },
    "witness": {
      "kind": "qubo-v1",
      "assignmentIndex": "1",
      "variableCount": 3,
      "energy": "-4",
      "bits": [1, 0, 0]
    },
    "proveOptimality": true,
    "z3TimeoutMs": 30000
  }')

echo "QUBO Response:"
echo "$QUBO_RESPONSE" | jq .

if echo "$QUBO_RESPONSE" | grep -q '"status":"SAT"'; then
  echo "✓ QUBO solver working (real Z3)"
  PROOF_HASH=$(echo "$QUBO_RESPONSE" | jq -r '.proof_hash')
  CERT_LEVEL=$(echo "$QUBO_RESPONSE" | jq -r '.certificate_level')
  echo "  Proof Hash: $PROOF_HASH"
  echo "  Certificate: $CERT_LEVEL"
else
  echo "✗ QUBO solver returned unexpected response"
  exit 1
fi
echo ""

# =========================================================================
# STEP 9: Output Summary
# =========================================================================

echo "======================================================================="
echo "✓ Z3 Solver Service Successfully Deployed"
echo "======================================================================="
echo ""
echo "Service Details:"
echo "  Project ID:        $PROJECT_ID"
echo "  Service Name:      $SERVICE_NAME"
echo "  Region:            $REGION"
echo "  Service URL:       $SERVICE_URL"
echo "  Shared Secret:     ${SECRET:0:16}... (saved in output)"
echo ""
echo "Next Steps:"
echo "  1. SAVE THE SECRET ABOVE - you'll need it for:"
echo "     - Cloud Run environment variable: DSG_SOLVER_SHARED_SECRET"
echo "     - Render environment variable:   DSG_SOLVER_SHARED_SECRET"
echo ""
echo "  2. Add to Render control-plane environment variables:"
echo "     DSG_Z3_SOLVER_URL=$SERVICE_URL"
echo "     DSG_SOLVER_SHARED_SECRET=$SECRET"
echo "     DSG_BACKEND_API_KEY=$(openssl rand -hex 32)"
echo ""
echo "  3. Commit /api/dsg/v1/verify endpoint to Render control-plane"
echo ""
echo "  4. Update Cinema BuildConfig with:"
echo "     DSG_BACKEND_API_KEY=<from-step-2-above>"
echo ""
echo "======================================================================="
echo ""
echo "Cloud Run Logs:"
gcloud run services logs read $SERVICE_NAME \
  --region=$REGION \
  --project=$PROJECT_ID \
  --limit=10

echo ""
echo "✓ Deployment complete!"
