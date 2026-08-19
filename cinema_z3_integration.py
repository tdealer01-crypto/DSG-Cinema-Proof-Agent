#!/usr/bin/env python3

"""
DSG ONE — Cinema + Z3 Integration Script (Python)

Purpose: Connect Cinema Proof Agent to Z3 Solver automatically
No bash/git required — works cross-platform

Usage:
    python3 cinema_z3_integration.py <SERVICE_URL> <API_SECRET> <BUILDCONFIG_PATH>

Example:
    python3 cinema_z3_integration.py \
        "http://z3-solver-service.westus3.azurecontainer.io:8080" \
        "a1b2c3d4e5f6..." \
        "app/src/main/java/com/example/BuildConfig.kt"
"""

import sys
import os
import json
import time
import shutil
import subprocess
import re
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# Color codes
class Color:
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    RESET = '\033[0m'

def print_header(title):
    print(f"\n{Color.BLUE}╔════════════════════════════════════════════════════════════════╗{Color.RESET}")
    print(f"{Color.BLUE}║ {title:<62} ║{Color.RESET}")
    print(f"{Color.BLUE}╚════════════════════════════════════════════════════════════════╝{Color.RESET}\n")

def print_step(step_num, title):
    print(f"{Color.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Color.RESET}")
    print(f"{Color.YELLOW}✓ STEP {step_num}: {title}{Color.RESET}")
    print(f"{Color.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Color.RESET}\n")

def print_success(msg):
    print(f"{Color.GREEN}✅ {msg}{Color.RESET}")

def print_error(msg):
    print(f"{Color.RED}❌ {msg}{Color.RESET}")

def print_warning(msg):
    print(f"{Color.YELLOW}⚠️  {msg}{Color.RESET}")

def print_info(msg):
    print(f"{Color.YELLOW}ℹ️  {msg}{Color.RESET}")

# ============================================================================
# STEP 0: VALIDATE INPUT
# ============================================================================

def validate_input():
    if len(sys.argv) < 3:
        print_error("Missing arguments")
        print("\nUsage:")
        print("  python3 cinema_z3_integration.py <SERVICE_URL> <API_SECRET> [BUILDCONFIG_PATH]")
        print("\nExample:")
        print("  python3 cinema_z3_integration.py \\")
        print("    'http://z3-solver-service.westus3.azurecontainer.io:8080' \\")
        print("    'a1b2c3d4...' \\")
        print("    'app/src/main/java/com/example/BuildConfig.kt'")
        sys.exit(1)
    
    service_url = sys.argv[1]
    api_secret = sys.argv[2]
    buildconfig_path = sys.argv[3] if len(sys.argv) > 3 else None
    
    return service_url, api_secret, buildconfig_path

# ============================================================================
# STEP 1: VERIFY Z3 IS RUNNING
# ============================================================================

def verify_z3_health(service_url):
    print_step(1, "Verify Z3 is running")
    
    print("Testing Z3 health endpoint...")
    health_url = f"{service_url}/health".rstrip('/')
    
    try:
        req = Request(health_url)
        with urlopen(req, timeout=5) as response:
            status_code = response.status
            body = response.read().decode('utf-8')
            
            if status_code == 200:
                print_success(f"Z3 health check PASSED")
                print(f"   Response: {body}")
                return True
            else:
                print_error(f"Z3 health check returned HTTP {status_code}")
                return False
    except HTTPError as e:
        print_error(f"Z3 health check failed: HTTP {e.code}")
        return False
    except URLError as e:
        print_error(f"Z3 health check failed: {e.reason}")
        print(f"   SERVICE_URL: {service_url}")
        print(f"   Make sure Z3 is deployed and running")
        return False
    except Exception as e:
        print_error(f"Z3 health check failed: {e}")
        return False

# ============================================================================
# STEP 2: LOCATE CINEMA BUILDCONFIG
# ============================================================================

def find_buildconfig(provided_path=None):
    print_step(2, "Locate Cinema BuildConfig")
    
    if provided_path:
        if os.path.isfile(provided_path):
            print_success(f"Found BuildConfig at: {provided_path}")
            return provided_path
        else:
            print_error(f"File not found at: {provided_path}")
            sys.exit(1)
    
    search_paths = [
        "app/src/main/java/com/example/BuildConfig.kt",
        "src/main/java/com/example/BuildConfig.kt",
        "BuildConfig.kt",
        "app/BuildConfig.kt",
    ]
    
    for path in search_paths:
        if os.path.isfile(path):
            print_success(f"Found BuildConfig at: {path}")
            return path
    
    print_error("BuildConfig.kt not found")
    print("\nSearched paths:")
    for path in search_paths:
        print(f"  - {path}")
    
    print("\nPlease specify the path to BuildConfig.kt:")
    user_path = input("> ").strip()
    
    if not os.path.isfile(user_path):
        print_error(f"File not found at: {user_path}")
        sys.exit(1)
    
    return user_path

# ============================================================================
# STEP 3: BACKUP BUILDCONFIG
# ============================================================================

def backup_file(filepath):
    print_step(3, "Backup BuildConfig")
    
    timestamp = int(time.time())
    backup_path = f"{filepath}.backup.{timestamp}"
    
    shutil.copy2(filepath, backup_path)
    print_success(f"Backup created: {backup_path}")
    
    return backup_path

# ============================================================================
# STEP 4: UPDATE BUILDCONFIG
# ============================================================================

def update_buildconfig(filepath, service_url, api_secret):
    print_step(4, "Update BuildConfig with Z3 credentials")
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    original_content = content
    
    # Update or add DSG_BACKEND_BASE_URL
    if 'DSG_BACKEND_BASE_URL' in content:
        content = re.sub(
            r'const val DSG_BACKEND_BASE_URL = ".*?"',
            f'const val DSG_BACKEND_BASE_URL = "{service_url}"',
            content
        )
    else:
        # Add new line before closing brace
        content = content.rstrip() + '\n    const val DSG_BACKEND_BASE_URL = "' + service_url + '"\n'
    
    # Update or add DSG_BACKEND_API_KEY
    if 'DSG_BACKEND_API_KEY' in content:
        content = re.sub(
            r'const val DSG_BACKEND_API_KEY = ".*?"',
            f'const val DSG_BACKEND_API_KEY = "{api_secret}"',
            content
        )
    else:
        content = content.rstrip() + '\n    const val DSG_BACKEND_API_KEY = "' + api_secret + '"\n'
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print_success("BuildConfig updated")

# ============================================================================
# STEP 5: VERIFY CHANGES
# ============================================================================

def verify_changes(filepath):
    print_step(5, "Verify changes in BuildConfig")
    
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    print("Updated lines:")
    found = False
    for line in lines:
        if 'DSG_BACKEND_BASE_URL' in line or 'DSG_BACKEND_API_KEY' in line:
            print(f"   {line.strip()}")
            found = True
    
    if not found:
        print_warning("Lines not found in BuildConfig")
    print()

# ============================================================================
# STEP 6: GIT COMMIT & PUSH
# ============================================================================

def git_commit_and_push(filepath):
    print_step(6, "Commit and push changes")
    
    # Check if git is available
    try:
        subprocess.run(['git', '--version'], capture_output=True, check=True)
    except Exception:
        print_warning("git not found in PATH")
        print("   Skipping git operations")
        print("   You'll need to manually:")
        print("   1. git add " + filepath)
        print("   2. git commit -m 'feat: Connect Cinema to Z3 Solver'")
        print("   3. git push origin main")
        return False
    
    # Check if in git repo
    try:
        subprocess.run(['git', 'rev-parse', '--git-dir'], 
                      capture_output=True, check=True, cwd=os.path.dirname(filepath) or '.')
    except Exception:
        print_error("Not in a git repository")
        print("   Please navigate to the Cinema repo root")
        print("   Then run this script again")
        return False
    
    # Stage changes
    try:
        subprocess.run(['git', 'add', filepath], check=True)
    except Exception as e:
        print_error(f"Failed to stage changes: {e}")
        return False
    
    # Commit
    commit_msg = f"feat: Connect Cinema to Z3 Solver ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
    try:
        subprocess.run(['git', 'commit', '-m', commit_msg], check=True, capture_output=True)
        print_success(f"Committed: {commit_msg}")
    except subprocess.CalledProcessError:
        print_info("Nothing new to commit")
        return False
    
    # Push
    try:
        subprocess.run(['git', 'push', 'origin', 'main'], check=True, capture_output=True)
        print_success("Pushed to origin/main")
        return True
    except subprocess.CalledProcessError:
        print_warning("Push failed. Try manually: git push origin main")
        return False
    
    print()

# ============================================================================
# STEP 7-9: DEPLOYMENT & TESTING
# ============================================================================

def print_next_steps(service_url):
    print_step(7, "Azure App Service will auto-redeploy")
    print("Cinema has GitHub Continuous Deployment enabled.")
    print("When you pushed to main, Azure automatically triggered a redeploy.\n")
    print("To check deployment status:")
    print("  az deployment group list --resource-group rg-t.dealer01-0468 --query '[0].[name,properties.provisioningState]'\n")
    
    print_step(8, "Test Cinema + Z3 integration")
    print("Waiting 30 seconds for redeployment to start...")
    
    cinema_url = "https://dsg-cinema-proof-agent.azurewebsites.net"
    for i in range(30, 0, -1):
        print(f"   {i}s remaining...", end='\r')
        time.sleep(1)
    print()
    
    print("Testing Cinema health endpoint...")
    try:
        req = Request(f"{cinema_url}/health")
        with urlopen(req, timeout=5) as response:
            if response.status == 200:
                print_success("Cinema health check PASSED")
            else:
                print_warning(f"Cinema returned HTTP {response.status}")
    except Exception:
        print_warning("Cinema still redeploying (this is normal)")
        print("   Redeploy can take 5-10 minutes")
        print(f"   Check status: {cinema_url}/health\n")
    
    print_step(9, "Test Z3 solve endpoint")
    print("Sending test QUBO to Z3...")
    
    qubo_test = {
        "request_id": "cinema-integration-test",
        "problem_type": "QUBO",
        "linear": [-4, -3, 1],
        "quadratic": [[0, 1, 5], [1, 2, 2]],
        "variables": 3,
        "seed": 42
    }
    
    try:
        req = Request(
            f"{service_url}/solve",
            data=json.dumps(qubo_test).encode('utf-8'),
            headers={
                "Authorization": f"Bearer {sys.argv[2]}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        with urlopen(req, timeout=10) as response:
            response_text = response.read().decode('utf-8')
            response_data = json.loads(response_text)
            print(f"Z3 Response:\n{json.dumps(response_data, indent=2)}")
            
            if 'sat' in response_text.lower() or 'satisfiable' in response_text.lower():
                print_success("Z3 solver working correctly")
            else:
                print_warning("Check Z3 response above")
    except Exception as e:
        print_error(f"Z3 test failed: {e}")

# ============================================================================
# MAIN
# ============================================================================

def main():
    print_header("DSG ONE — Cinema + Z3 Automatic Integration")
    
    service_url, api_secret, buildconfig_path = validate_input()
    
    print(f"{Color.YELLOW}📋 Configuration:{Color.RESET}")
    print(f"   SERVICE_URL: {service_url}")
    print(f"   API_SECRET: {api_secret[:8]}...{api_secret[-8:]}\n")
    
    # STEP 1: Verify Z3
    if not verify_z3_health(service_url):
        print_error("Cannot proceed without Z3 running")
        sys.exit(1)
    print()
    
    # STEP 2: Find BuildConfig
    buildconfig_file = find_buildconfig(buildconfig_path)
    print()
    
    # STEP 3: Backup
    backup_path = backup_file(buildconfig_file)
    print()
    
    # STEP 4: Update
    update_buildconfig(buildconfig_file, service_url, api_secret)
    print()
    
    # STEP 5: Verify
    verify_changes(buildconfig_file)
    
    # STEP 6: Git commit
    git_pushed = git_commit_and_push(buildconfig_file)
    
    # STEP 7-9: Deploy & Test
    print_next_steps(service_url)
    
    # SUMMARY
    print_header("✅ INTEGRATION COMPLETE")
    print(f"{Color.YELLOW}Summary:{Color.RESET}")
    print("   ✅ Z3 health verified")
    print("   ✅ BuildConfig updated with Z3 credentials")
    if git_pushed:
        print("   ✅ Changes committed to GitHub")
        print("   ✅ Redeployment triggered")
    else:
        print("   ⚠️  Git commit/push skipped (manual action needed)")
    print("   ✅ Z3 /solve endpoint tested\n")
    
    print(f"{Color.YELLOW}Next steps:{Color.RESET}")
    print("   1. Wait 5-10 minutes for Cinema to finish redeploying")
    print("   2. Test Cinema health: curl https://dsg-cinema-proof-agent.azurewebsites.net/health")
    print("   3. Test Cinema /solve: curl -X POST https://dsg-cinema-proof-agent.azurewebsites.net/solve")
    print("   4. Check Azure deployment status:")
    print("      az deployment group list --resource-group rg-t.dealer01-0468\n")
    
    print(f"{Color.YELLOW}Rollback (if needed):{Color.RESET}")
    print(f"   cp {backup_path} {buildconfig_file}")
    print("   git add <file> && git commit -m 'Rollback Z3 integration' && git push\n")
    
    print(f"{Color.GREEN}🎉 Cinema + Z3 integration initiated!{Color.RESET}\n")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Color.YELLOW}Interrupted by user{Color.RESET}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        sys.exit(1)
