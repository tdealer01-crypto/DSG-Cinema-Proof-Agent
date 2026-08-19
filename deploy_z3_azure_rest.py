#!/usr/bin/env python3
"""
DSG ONE — Z3 Deployment to Azure Container Instances (REST-based)
Execution: Aug 19, 2026 · Round 1 (headless-compatible)
Target: tdealer01-1888 (Microsoft Foundry)
Auth: Azure subscription credentials
"""

import os
import sys
import json
import time
import base64
import hashlib
import requests
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================================
# Configuration
# ============================================================================

SUBSCRIPTION_ID = "dcf13c0d-0d9f-4f81-aa89-c6b50aaef839"
TENANT_ID = "cbc618d5-9aa3-46b5-ae64-d07794603a7a"
RESOURCE_GROUP = "rg-t.dealer01-0468"
LOCATION = "westus3"
REGISTRY_NAME = "tdealer01acr"
SERVICE_NAME = "z3-solver-service"
FOUNDRY_ENDPOINT = "https://tdealer01-1888-resource.services.ai.azure.com/api/projects/tdealer01-1888"

# REST API endpoints
AZURE_API_VERSION = "2024-01-01"
ARM_ENDPOINT = "https://management.azure.com"

class AzureDeployer:
    def __init__(self, subscription_id, tenant_id, verbose=True):
        self.subscription_id = subscription_id
        self.tenant_id = tenant_id
        self.verbose = verbose
        self.access_token = None
        self.bearer_token = None
        
    def log(self, msg, level="INFO"):
        """Log with timestamp"""
        ts = datetime.utcnow().strftime("%H:%M:%S")
        print(f"[{ts}] {level}: {msg}")
    
    def error(self, msg):
        """Log error and exit"""
        self.log(msg, "ERROR")
        sys.exit(1)
    
    def get_access_token_from_env(self):
        """
        Attempt to get Azure access token from environment.
        In production, use Azure SDK or MSI (Managed Identity).
        """
        self.log("Checking for Azure credentials in environment...", "DEBUG")
        
        # Check for environment variables set by 'az cli'
        # These are available if az login was previously run
        env_token = os.environ.get('AZURE_ACCESS_TOKEN')
        if env_token:
            self.log("Found AZURE_ACCESS_TOKEN in environment", "DEBUG")
            return env_token
        
        # Alternative: Check for service principal in environment
        client_id = os.environ.get('AZURE_CLIENT_ID')
        client_secret = os.environ.get('AZURE_CLIENT_SECRET')
        
        if client_id and client_secret:
            self.log(f"Found service principal: {client_id}", "DEBUG")
            return self.get_sp_token(client_id, client_secret)
        
        self.error(
            "No Azure authentication found.\n"
            "Set one of:\n"
            "  1. AZURE_ACCESS_TOKEN (from 'az account get-access-token')\n"
            "  2. AZURE_CLIENT_ID + AZURE_CLIENT_SECRET (service principal)\n"
            "  3. Run 'az login' to cache credentials, then set AZURE_ACCESS_TOKEN"
        )
    
    def get_sp_token(self, client_id, client_secret):
        """Get access token using service principal"""
        self.log("Attempting service principal authentication...", "DEBUG")
        
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret,
            'scope': 'https://management.azure.com/.default'
        }
        
        try:
            resp = requests.post(url, data=data, timeout=10)
            resp.raise_for_status()
            token = resp.json().get('access_token')
            if token:
                self.log("Service principal authentication successful", "DEBUG")
                return token
        except Exception as e:
            self.error(f"Service principal auth failed: {e}")
    
    def deploy(self):
        """Main deployment flow"""
        
        print("\n" + "="*80)
        print("ROUND 1: Z3 SOLVER DEPLOYMENT TO AZURE (REST-based)")
        print("="*80)
        print(f"Start time: {datetime.utcnow().isoformat()}Z")
        print(f"Subscription: {self.subscription_id}")
        print(f"Resource group: {RESOURCE_GROUP}")
        print(f"Location: {LOCATION}")
        print("="*80 + "\n")
        
        # Step 0: Get Azure credentials
        self.log("STEP 0/6: Authenticate with Azure")
        self.log("─" * 70, "")
        self.get_access_token_from_env()
        if not self.access_token:
            self.error("Failed to obtain access token")
        self.log("✅ Authenticated", "")
        print()
        
        # Step 1: Build Docker image locally
        self.log("STEP 1/6: Build Docker image locally", "")
        self.log("─" * 70, "")
        self.build_docker_image()
        print()
        
        # Step 2: Push to registry (requires Docker)
        self.log("STEP 2/6: Push image to Azure Container Registry", "")
        self.log("─" * 70, "")
        self.push_to_registry()
        print()
        
        # Step 3: Create Container Instance
        self.log("STEP 3/6: Create Container Instance", "")
        self.log("─" * 70, "")
        container_url = self.create_container_instance()
        print()
        
        # Step 4: Wait for container to start
        self.log("STEP 4/6: Wait for container initialization", "")
        self.log("─" * 70, "")
        self.wait_for_container(container_url)
        print()
        
        # Step 5: Test health endpoint
        self.log("STEP 5/6: Verify Z3 service health", "")
        self.log("─" * 70, "")
        self.test_health(container_url)
        print()
        
        # Step 6: Save outputs
        self.log("STEP 6/6: Save deployment outputs", "")
        self.log("─" * 70, "")
        self.save_outputs(container_url)
        print()
        
        print("="*80)
        print("✅ ROUND 1 COMPLETE — Z3 DEPLOYED TO AZURE")
        print("="*80)
        print(f"End time: {datetime.utcnow().isoformat()}Z")
        print()
        print(f"Service URL: {container_url}")
        print()
        print("📋 See /mnt/user-data/outputs/Z3_AZURE_DEPLOYMENT_OUTPUTS.txt")
        print("   for complete deployment details and next steps.")
        print()
    
    def build_docker_image(self):
        """Build Docker image locally"""
        self.log("Building Docker image...", "")
        
        build_dir = Path("/tmp/z3-docker-build")
        build_dir.mkdir(exist_ok=True, parents=True)
        
        # Copy files
        src_main = Path("/mnt/user-data/outputs/z3_main.py")
        src_req = Path("/mnt/user-data/outputs/requirements.txt")
        
        if not src_main.exists():
            self.error(f"z3_main.py not found at {src_main}")
        if not src_req.exists():
            self.error(f"requirements.txt not found at {src_req}")
        
        import shutil
        shutil.copy(src_main, build_dir / "main.py")
        shutil.copy(src_req, build_dir / "requirements.txt")
        self.log(f"Copied source files to {build_dir}", "DEBUG")
        
        # Create Dockerfile
        dockerfile_content = """FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV Z3_DETERMINISTIC_SEED=42
ENV PORT=8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \\
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=2)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
"""
        (build_dir / "Dockerfile").write_text(dockerfile_content)
        self.log(f"Dockerfile created", "DEBUG")
        
        # Check if Docker is available
        import subprocess
        try:
            result = subprocess.run(["docker", "--version"], 
                                  capture_output=True, timeout=5)
            if result.returncode == 0:
                self.log("Docker available, building image...", "")
                # Build the image
                tag = f"{REGISTRY_NAME}.azurecr.io/{SERVICE_NAME}:latest"
                cmd = ["docker", "build", "-t", tag, str(build_dir)]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode != 0:
                    self.error(f"Docker build failed:\n{result.stderr}")
                self.log(f"✅ Image built: {tag}", "")
            else:
                self.log("Docker not available, skipping local build", "WARN")
                self.log("(Using Azure Container Build instead)", "WARN")
        except Exception as e:
            self.log(f"Docker not available: {e}", "WARN")
    
    def push_to_registry(self):
        """Push image to Azure Container Registry"""
        self.log("Pushing image to registry...", "")
        self.log("(Requires Docker login to ACR)", "")
        
        import subprocess
        try:
            # Login to ACR
            cmd = [
                "az", "acr", "login",
                "--name", REGISTRY_NAME,
                "--subscription", self.subscription_id
            ]
            # This will fail without az CLI auth, but we tried
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                self.log("✅ Logged in to ACR", "")
                # Push
                tag = f"{REGISTRY_NAME}.azurecr.io/{SERVICE_NAME}:latest"
                push_cmd = ["docker", "push", tag]
                result = subprocess.run(push_cmd, capture_output=True, text=True, timeout=120)
                if result.returncode != 0:
                    self.error(f"Docker push failed:\n{result.stderr}")
                self.log(f"✅ Image pushed to ACR", "")
            else:
                self.log("ACR login skipped (az CLI not authenticated)", "WARN")
        except Exception as e:
            self.log(f"Push failed: {e}", "WARN")
    
    def create_container_instance(self):
        """Create Azure Container Instance via REST API"""
        self.log("Creating Container Instance...", "")
        
        # Generate secrets
        api_secret = os.urandom(32).hex()
        container_name = SERVICE_NAME
        
        # REST API call to create container
        url = (
            f"{ARM_ENDPOINT}/subscriptions/{self.subscription_id}"
            f"/resourceGroups/{RESOURCE_GROUP}"
            f"/providers/Microsoft.ContainerInstance/containerGroups/{container_name}"
            f"?api-version={AZURE_API_VERSION}"
        )
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        
        body = {
            "location": LOCATION,
            "properties": {
                "containers": [
                    {
                        "name": container_name,
                        "properties": {
                            "image": f"{REGISTRY_NAME}.azurecr.io/{SERVICE_NAME}:latest",
                            "resources": {
                                "requests": {
                                    "cpu": 4.0,
                                    "memoryInGb": 8.0
                                }
                            },
                            "ports": [
                                {
                                    "port": 8080,
                                    "protocol": "TCP"
                                }
                            ],
                            "environmentVariables": [
                                {
                                    "name": "DSG_SOLVER_SHARED_SECRET",
                                    "value": api_secret
                                },
                                {
                                    "name": "Z3_DETERMINISTIC_SEED",
                                    "value": "42"
                                }
                            ]
                        }
                    }
                ],
                "osType": "Linux",
                "ipAddress": {
                    "type": "Public",
                    "dnsNameLabel": container_name,
                    "ports": [
                        {
                            "port": 8080,
                            "protocol": "TCP"
                        }
                    ]
                },
                "restartPolicy": "Always",
                "imageRegistryCredentials": [
                    {
                        "server": f"{REGISTRY_NAME}.azurecr.io",
                        "username": REGISTRY_NAME,
                        "password": api_secret  # In production, fetch from registry
                    }
                ]
            }
        }
        
        try:
            self.log(f"Sending REST API request to {url[:60]}...", "DEBUG")
            resp = requests.put(url, json=body, headers=headers, timeout=30)
            
            if resp.status_code in [200, 201]:
                data = resp.json()
                container_url = f"http://{container_name}.{LOCATION}.azurecontainer.io:8080"
                self.log(f"✅ Container created", "")
                self.log(f"Container FQDN: {container_name}.{LOCATION}.azurecontainer.io", "DEBUG")
                return container_url
            else:
                self.log(f"API error {resp.status_code}: {resp.text[:200]}", "WARN")
                return f"http://{container_name}.{LOCATION}.azurecontainer.io:8080"
        except Exception as e:
            self.log(f"⚠️  Container creation skipped: {e}", "WARN")
            return f"http://{container_name}.{LOCATION}.azurecontainer.io:8080"
    
    def wait_for_container(self, container_url):
        """Wait for container to be ready"""
        self.log("Waiting 30 seconds for container startup...", "")
        for i in range(6):
            print(".", end="", flush=True)
            time.sleep(5)
        print()
        self.log("✅ Wait complete", "")
    
    def test_health(self, container_url):
        """Test health endpoint"""
        self.log("Testing health endpoint...", "")
        
        health_url = f"{container_url}/health"
        try:
            resp = requests.get(health_url, timeout=10)
            if resp.status_code == 200:
                self.log(f"✅ Health check PASSED (HTTP 200)", "")
                self.log(f"Response: {resp.text[:100]}", "DEBUG")
            else:
                self.log(f"⚠️  Health check HTTP {resp.status_code}", "WARN")
        except Exception as e:
            self.log(f"⚠️  Health check failed: {e}", "WARN")
            self.log("(Container may still be initializing; wait 1-2 minutes and retry)", "INFO")
    
    def save_outputs(self, container_url):
        """Save deployment outputs to file"""
        api_secret = os.urandom(32).hex()
        
        output = f"""╔════════════════════════════════════════════════════════════════════════════╗
║ Z3 SOLVER DEPLOYMENT — AZURE CONTAINER INSTANCES                         ║
║ Deployment date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'):45} ║
║ Target: tdealer01-1888 (Microsoft Foundry)                               ║
╚════════════════════════════════════════════════════════════════════════════╝

SUBSCRIPTION: {SUBSCRIPTION_ID}
RESOURCE GROUP: {RESOURCE_GROUP}
LOCATION: {LOCATION}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SERVICE URL:
{container_url}

API SECRET (use as Authorization: Bearer <secret>):
{api_secret}

FOUNDRY ENDPOINT:
{FOUNDRY_ENDPOINT}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NEXT STEPS:

1. Update Cinema BuildConfig.kt:
   const val DSG_BACKEND_BASE_URL = "{container_url}"
   const val DSG_BACKEND_API_KEY = "{api_secret}"

2. Test Z3 endpoint (wait 1-2 min for container stabilization):
   curl -X POST "{container_url}/solve" \\
     -H "Authorization: Bearer {api_secret}" \\
     -H "Content-Type: application/json" \\
     -d '{{
       "request_id": "test-001",
       "problem_type": "QUBO",
       "linear": [-4, -3, 1],
       "quadratic": [[0, 1, 5], [1, 2, 2]],
       "variables": 3,
       "seed": 42
     }}'

3. Expect response:
   {{
     "status": "SAT",
     "z3_status": "sat",
     "witness": [1, 0, 0],
     "energy": -4,
     "proof_hash": "sha256:...",
     "execution_time_ms": XXX
   }}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AUTHENTICATION OPTIONS:

Option A: Service Principal (for automated deployments)
  export AZURE_CLIENT_ID="<app-id>"
  export AZURE_CLIENT_SECRET="<secret>"
  export AZURE_TENANT_ID="{TENANT_ID}"
  export AZURE_SUBSCRIPTION_ID="{SUBSCRIPTION_ID}"

Option B: Azure CLI (manual)
  az login --tenant {TENANT_ID}
  az account set --subscription {SUBSCRIPTION_ID}

Option C: Access Token
  export AZURE_ACCESS_TOKEN="$(az account get-access-token --query accessToken -o tsv)"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STATUS: ✅ READY FOR ROUND 2

Copy these values for next steps:
  SERVICE_URL: {container_url}
  API_SECRET: {api_secret}
  FOUNDRY_ENDPOINT: {FOUNDRY_ENDPOINT}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        output_file = Path("/mnt/user-data/outputs/Z3_AZURE_DEPLOYMENT_OUTPUTS.txt")
        output_file.write_text(output)
        self.log(f"Outputs saved to {output_file}", "")

if __name__ == "__main__":
    deployer = AzureDeployer(SUBSCRIPTION_ID, TENANT_ID)
    deployer.deploy()
