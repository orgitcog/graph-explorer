#!/usr/bin/env python3
"""
God Mode - Rapid Azure AD & GitHub Enterprise Bulk Provisioning

Deploy entire organizational structures in seconds:
- Multiple tenants (via Azure subscription)
- Organizations/Groups
- Users with roles
- Applications and service principals
- GitHub Enterprise orgs and repos

Usage:
    python god_mode.py provision --config infrastructure.yaml
    python god_mode.py provision --tenants 3 --orgs 9 --users 50
    python god_mode.py sync --source azure --target github
"""

import os
import sys
import json
import yaml
import argparse
import asyncio
import aiohttp
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table
    from rich.panel import Panel
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# Configuration
CONFIG_DIR = Path.home() / ".godmode"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "provision.log"

# API Endpoints
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
GRAPH_BETA_ENDPOINT = "https://graph.microsoft.com/beta"
AZURE_MGMT_ENDPOINT = "https://management.azure.com"

# ANSI colors for non-rich output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

console = Console() if HAS_RICH else None

@dataclass
class ProvisioningResult:
    """Result of a provisioning operation"""
    success: bool
    resource_type: str
    resource_id: str
    resource_name: str
    details: Dict = field(default_factory=dict)
    error: Optional[str] = None

@dataclass
class InfrastructureSpec:
    """Specification for infrastructure to provision"""
    tenants: List[Dict] = field(default_factory=list)
    organizations: List[Dict] = field(default_factory=list)
    users: List[Dict] = field(default_factory=list)
    groups: List[Dict] = field(default_factory=list)
    applications: List[Dict] = field(default_factory=list)
    github_orgs: List[Dict] = field(default_factory=list)
    github_repos: List[Dict] = field(default_factory=list)


class GodModeClient:
    """
    God Mode API Client for rapid bulk provisioning
    """
    
    def __init__(self):
        self.tenant_id = os.environ.get("AZURE_TENANT_ID")
        self.client_id = os.environ.get("AZURE_CLIENT_ID")
        self.client_secret = os.environ.get("AZURE_CLIENT_SECRET")
        self.subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID")
        self.ghe_token = os.environ.get("GHE_ADMIN_TOKEN") or os.environ.get("beast")
        self.ghe_url = os.environ.get("GHE_INSTANCE_URL", "https://api.github.com")
        
        self._graph_token = None
        self._mgmt_token = None
        self._session = None
        self.results: List[ProvisioningResult] = []
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
    
    async def _get_token(self, resource: str) -> str:
        """Get access token for a resource"""
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": f"{resource}/.default",
            "grant_type": "client_credentials"
        }
        
        async with self._session.post(token_url, data=data) as response:
            if response.status == 200:
                result = await response.json()
                return result.get("access_token")
            else:
                text = await response.text()
                raise Exception(f"Token acquisition failed: {response.status} - {text}")
    
    async def get_graph_token(self) -> str:
        """Get Microsoft Graph token"""
        if not self._graph_token:
            self._graph_token = await self._get_token("https://graph.microsoft.com")
        return self._graph_token
    
    async def graph_request(self, method: str, endpoint: str, data: Dict = None, beta: bool = False) -> Dict:
        """Make a Graph API request"""
        token = await self.get_graph_token()
        base = GRAPH_BETA_ENDPOINT if beta else GRAPH_ENDPOINT
        url = f"{base}{endpoint}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with self._session.request(method, url, headers=headers, json=data) as response:
            if response.status == 204:
                return {}
            result = await response.json()
            if response.status >= 400:
                raise Exception(f"Graph API error: {response.status} - {result}")
            return result
    
    async def github_request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make a GitHub API request"""
        url = f"{self.ghe_url}{endpoint}"
        
        headers = {
            "Authorization": f"token {self.ghe_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        async with self._session.request(method, url, headers=headers, json=data) as response:
            if response.status == 204:
                return {}
            result = await response.json()
            if response.status >= 400:
                raise Exception(f"GitHub API error: {response.status} - {result}")
            return result
    
    # ==================== USER PROVISIONING ====================
    
    async def create_user(self, user_spec: Dict) -> ProvisioningResult:
        """Create a single user"""
        try:
            # Generate a random password
            import secrets
            import string
            password = ''.join(secrets.choice(string.ascii_letters + string.digits + "!@#$%") for _ in range(16))
            
            user_data = {
                "accountEnabled": True,
                "displayName": user_spec.get("displayName", user_spec.get("name", "New User")),
                "mailNickname": user_spec.get("mailNickname", user_spec.get("username", "newuser")),
                "userPrincipalName": user_spec.get("userPrincipalName", f"{user_spec.get('username', 'newuser')}@{self.tenant_id}.onmicrosoft.com"),
                "passwordProfile": {
                    "forceChangePasswordNextSignIn": True,
                    "password": password
                }
            }
            
            # Add optional fields
            if user_spec.get("jobTitle"):
                user_data["jobTitle"] = user_spec["jobTitle"]
            if user_spec.get("department"):
                user_data["department"] = user_spec["department"]
            if user_spec.get("officeLocation"):
                user_data["officeLocation"] = user_spec["officeLocation"]
            
            result = await self.graph_request("POST", "/users", user_data)
            
            return ProvisioningResult(
                success=True,
                resource_type="user",
                resource_id=result.get("id"),
                resource_name=result.get("displayName"),
                details={"userPrincipalName": result.get("userPrincipalName"), "tempPassword": password}
            )
        except Exception as e:
            return ProvisioningResult(
                success=False,
                resource_type="user",
                resource_id="",
                resource_name=user_spec.get("displayName", "Unknown"),
                error=str(e)
            )
    
    async def create_users_bulk(self, users: List[Dict], concurrency: int = 10) -> List[ProvisioningResult]:
        """Create multiple users concurrently"""
        semaphore = asyncio.Semaphore(concurrency)
        
        async def create_with_semaphore(user):
            async with semaphore:
                return await self.create_user(user)
        
        tasks = [create_with_semaphore(user) for user in users]
        return await asyncio.gather(*tasks)
    
    # ==================== GROUP PROVISIONING ====================
    
    async def create_group(self, group_spec: Dict) -> ProvisioningResult:
        """Create a security group or Microsoft 365 group"""
        try:
            group_data = {
                "displayName": group_spec.get("displayName", group_spec.get("name", "New Group")),
                "mailEnabled": group_spec.get("mailEnabled", False),
                "mailNickname": group_spec.get("mailNickname", group_spec.get("name", "newgroup").replace(" ", "").lower()),
                "securityEnabled": group_spec.get("securityEnabled", True),
            }
            
            # Microsoft 365 group
            if group_spec.get("groupTypes"):
                group_data["groupTypes"] = group_spec["groupTypes"]
            
            if group_spec.get("description"):
                group_data["description"] = group_spec["description"]
            
            result = await self.graph_request("POST", "/groups", group_data)
            
            return ProvisioningResult(
                success=True,
                resource_type="group",
                resource_id=result.get("id"),
                resource_name=result.get("displayName"),
                details={"mailNickname": result.get("mailNickname")}
            )
        except Exception as e:
            return ProvisioningResult(
                success=False,
                resource_type="group",
                resource_id="",
                resource_name=group_spec.get("displayName", "Unknown"),
                error=str(e)
            )
    
    async def create_groups_bulk(self, groups: List[Dict], concurrency: int = 10) -> List[ProvisioningResult]:
        """Create multiple groups concurrently"""
        semaphore = asyncio.Semaphore(concurrency)
        
        async def create_with_semaphore(group):
            async with semaphore:
                return await self.create_group(group)
        
        tasks = [create_with_semaphore(group) for group in groups]
        return await asyncio.gather(*tasks)
    
    # ==================== APPLICATION PROVISIONING ====================
    
    async def create_application(self, app_spec: Dict) -> ProvisioningResult:
        """Create an Azure AD application"""
        try:
            app_data = {
                "displayName": app_spec.get("displayName", app_spec.get("name", "New Application")),
                "signInAudience": app_spec.get("signInAudience", "AzureADMyOrg"),
            }
            
            if app_spec.get("web"):
                app_data["web"] = app_spec["web"]
            if app_spec.get("requiredResourceAccess"):
                app_data["requiredResourceAccess"] = app_spec["requiredResourceAccess"]
            
            result = await self.graph_request("POST", "/applications", app_data)
            
            return ProvisioningResult(
                success=True,
                resource_type="application",
                resource_id=result.get("id"),
                resource_name=result.get("displayName"),
                details={"appId": result.get("appId")}
            )
        except Exception as e:
            return ProvisioningResult(
                success=False,
                resource_type="application",
                resource_id="",
                resource_name=app_spec.get("displayName", "Unknown"),
                error=str(e)
            )
    
    # ==================== GITHUB PROVISIONING ====================
    
    async def create_github_org(self, org_spec: Dict) -> ProvisioningResult:
        """Create a GitHub organization (Enterprise only)"""
        try:
            # Note: Creating orgs requires GitHub Enterprise admin API
            org_data = {
                "login": org_spec.get("login", org_spec.get("name")),
                "admin": org_spec.get("admin", "admin"),
                "profile_name": org_spec.get("profile_name", org_spec.get("name"))
            }
            
            result = await self.github_request("POST", "/admin/organizations", org_data)
            
            return ProvisioningResult(
                success=True,
                resource_type="github_org",
                resource_id=str(result.get("id")),
                resource_name=result.get("login"),
                details={"html_url": result.get("html_url")}
            )
        except Exception as e:
            return ProvisioningResult(
                success=False,
                resource_type="github_org",
                resource_id="",
                resource_name=org_spec.get("login", "Unknown"),
                error=str(e)
            )
    
    async def create_github_repo(self, repo_spec: Dict) -> ProvisioningResult:
        """Create a GitHub repository"""
        try:
            org = repo_spec.get("org")
            repo_data = {
                "name": repo_spec.get("name"),
                "description": repo_spec.get("description", ""),
                "private": repo_spec.get("private", False),
                "auto_init": repo_spec.get("auto_init", True)
            }
            
            if org:
                endpoint = f"/orgs/{org}/repos"
            else:
                endpoint = "/user/repos"
            
            result = await self.github_request("POST", endpoint, repo_data)
            
            return ProvisioningResult(
                success=True,
                resource_type="github_repo",
                resource_id=str(result.get("id")),
                resource_name=result.get("full_name"),
                details={"html_url": result.get("html_url"), "clone_url": result.get("clone_url")}
            )
        except Exception as e:
            return ProvisioningResult(
                success=False,
                resource_type="github_repo",
                resource_id="",
                resource_name=repo_spec.get("name", "Unknown"),
                error=str(e)
            )
    
    # ==================== BULK PROVISIONING ====================
    
    async def provision_infrastructure(self, spec: InfrastructureSpec, progress_callback=None) -> Dict[str, List[ProvisioningResult]]:
        """Provision entire infrastructure from specification"""
        results = {
            "users": [],
            "groups": [],
            "applications": [],
            "github_orgs": [],
            "github_repos": []
        }
        
        total_items = (
            len(spec.users) + len(spec.groups) + len(spec.applications) +
            len(spec.github_orgs) + len(spec.github_repos)
        )
        
        completed = 0
        
        # Provision groups first (users may need to be added to them)
        if spec.groups:
            if progress_callback:
                progress_callback("groups", 0, len(spec.groups))
            results["groups"] = await self.create_groups_bulk(spec.groups)
            completed += len(spec.groups)
            if progress_callback:
                progress_callback("groups", len(spec.groups), len(spec.groups))
        
        # Provision users
        if spec.users:
            if progress_callback:
                progress_callback("users", 0, len(spec.users))
            results["users"] = await self.create_users_bulk(spec.users)
            completed += len(spec.users)
            if progress_callback:
                progress_callback("users", len(spec.users), len(spec.users))
        
        # Provision applications
        if spec.applications:
            if progress_callback:
                progress_callback("applications", 0, len(spec.applications))
            for app in spec.applications:
                result = await self.create_application(app)
                results["applications"].append(result)
            completed += len(spec.applications)
            if progress_callback:
                progress_callback("applications", len(spec.applications), len(spec.applications))
        
        # Provision GitHub orgs
        if spec.github_orgs:
            if progress_callback:
                progress_callback("github_orgs", 0, len(spec.github_orgs))
            for org in spec.github_orgs:
                result = await self.create_github_org(org)
                results["github_orgs"].append(result)
            completed += len(spec.github_orgs)
            if progress_callback:
                progress_callback("github_orgs", len(spec.github_orgs), len(spec.github_orgs))
        
        # Provision GitHub repos
        if spec.github_repos:
            if progress_callback:
                progress_callback("github_repos", 0, len(spec.github_repos))
            for repo in spec.github_repos:
                result = await self.create_github_repo(repo)
                results["github_repos"].append(result)
            completed += len(spec.github_repos)
            if progress_callback:
                progress_callback("github_repos", len(spec.github_repos), len(spec.github_repos))
        
        return results


def generate_infrastructure_spec(tenants: int = 1, orgs: int = 3, users_per_org: int = 10) -> InfrastructureSpec:
    """Generate an infrastructure specification for quick provisioning"""
    spec = InfrastructureSpec()
    
    # Generate organizations (groups)
    for i in range(orgs):
        org_name = f"Organization-{i+1:02d}"
        spec.groups.append({
            "displayName": org_name,
            "description": f"Auto-generated organization {i+1}",
            "mailEnabled": False,
            "securityEnabled": True,
            "mailNickname": f"org{i+1:02d}"
        })
        
        # Generate users for each org
        for j in range(users_per_org):
            user_num = i * users_per_org + j + 1
            spec.users.append({
                "displayName": f"User {user_num:03d}",
                "username": f"user{user_num:03d}",
                "mailNickname": f"user{user_num:03d}",
                "department": org_name,
                "jobTitle": ["Developer", "Manager", "Analyst", "Engineer", "Designer"][j % 5]
            })
    
    return spec


def generate_github_spec(orgs: int = 3, repos_per_org: int = 3) -> InfrastructureSpec:
    """Generate GitHub infrastructure specification"""
    spec = InfrastructureSpec()
    
    for i in range(orgs):
        org_name = f"org-{i+1:02d}"
        
        # Generate repos for each org
        for j in range(repos_per_org):
            spec.github_repos.append({
                "org": "orgitcog",  # Use existing org
                "name": f"{org_name}-repo-{j+1:02d}",
                "description": f"Auto-generated repository for {org_name}",
                "private": False,
                "auto_init": True
            })
    
    return spec


async def run_provisioning(spec: InfrastructureSpec):
    """Run the provisioning process"""
    print(f"\n{Colors.BOLD}God Mode - Bulk Provisioning{Colors.ENDC}")
    print("=" * 50)
    
    print(f"\nProvisioning:")
    print(f"  • {len(spec.groups)} groups/organizations")
    print(f"  • {len(spec.users)} users")
    print(f"  • {len(spec.applications)} applications")
    print(f"  • {len(spec.github_orgs)} GitHub organizations")
    print(f"  • {len(spec.github_repos)} GitHub repositories")
    
    start_time = datetime.now()
    
    async with GodModeClient() as client:
        if HAS_RICH:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                tasks = {}
                
                def progress_callback(resource_type, completed, total):
                    if resource_type not in tasks:
                        tasks[resource_type] = progress.add_task(f"[cyan]{resource_type}", total=total)
                    progress.update(tasks[resource_type], completed=completed)
                
                results = await client.provision_infrastructure(spec, progress_callback)
        else:
            def progress_callback(resource_type, completed, total):
                print(f"  {resource_type}: {completed}/{total}")
            
            results = await client.provision_infrastructure(spec, progress_callback)
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    # Print summary
    print(f"\n{Colors.BOLD}Provisioning Complete!{Colors.ENDC}")
    print(f"Duration: {duration:.2f} seconds")
    print()
    
    total_success = 0
    total_failed = 0
    
    for resource_type, resource_results in results.items():
        if not resource_results:
            continue
        
        success = sum(1 for r in resource_results if r.success)
        failed = sum(1 for r in resource_results if not r.success)
        total_success += success
        total_failed += failed
        
        status_color = Colors.GREEN if failed == 0 else Colors.YELLOW
        print(f"  {resource_type}: {status_color}{success} created{Colors.ENDC}, {Colors.RED if failed > 0 else ''}{failed} failed{Colors.ENDC if failed > 0 else ''}")
        
        # Show errors
        for r in resource_results:
            if not r.success:
                print(f"    {Colors.RED}✗ {r.resource_name}: {r.error}{Colors.ENDC}")
    
    print()
    print(f"Total: {Colors.GREEN}{total_success} created{Colors.ENDC}, {Colors.RED if total_failed > 0 else ''}{total_failed} failed{Colors.ENDC if total_failed > 0 else ''}")
    
    # Save results
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    results_file = CONFIG_DIR / f"provision_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    serializable_results = {}
    for k, v in results.items():
        serializable_results[k] = [
            {
                "success": r.success,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "resource_name": r.resource_name,
                "details": r.details,
                "error": r.error
            }
            for r in v
        ]
    
    with open(results_file, 'w') as f:
        json.dump(serializable_results, f, indent=2)
    
    print(f"\nResults saved to: {results_file}")
    
    return results


def cmd_provision(args):
    """Provision infrastructure"""
    if args.config:
        # Load from YAML config
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
        spec = InfrastructureSpec(**config)
    else:
        # Generate from command line args
        spec = generate_infrastructure_spec(
            tenants=args.tenants or 1,
            orgs=args.orgs or 3,
            users_per_org=args.users or 10
        )
        
        # Add GitHub resources if requested
        if args.github:
            github_spec = generate_github_spec(orgs=args.orgs or 3, repos_per_org=3)
            spec.github_repos = github_spec.github_repos
    
    asyncio.run(run_provisioning(spec))


def cmd_generate_config(args):
    """Generate a sample configuration file"""
    sample_config = {
        "groups": [
            {
                "displayName": "Engineering",
                "description": "Engineering team",
                "mailEnabled": False,
                "securityEnabled": True
            },
            {
                "displayName": "Sales",
                "description": "Sales team",
                "mailEnabled": False,
                "securityEnabled": True
            }
        ],
        "users": [
            {
                "displayName": "John Doe",
                "username": "johndoe",
                "department": "Engineering",
                "jobTitle": "Senior Developer"
            },
            {
                "displayName": "Jane Smith",
                "username": "janesmith",
                "department": "Sales",
                "jobTitle": "Account Manager"
            }
        ],
        "applications": [
            {
                "displayName": "Internal Dashboard",
                "signInAudience": "AzureADMyOrg"
            }
        ],
        "github_repos": [
            {
                "org": "orgitcog",
                "name": "sample-repo",
                "description": "Sample repository",
                "private": False
            }
        ]
    }
    
    output_file = args.output or "infrastructure.yaml"
    with open(output_file, 'w') as f:
        yaml.dump(sample_config, f, default_flow_style=False)
    
    print(f"Sample configuration saved to: {output_file}")


def cmd_status(args):
    """Check God Mode status and credentials"""
    print(f"\n{Colors.BOLD}God Mode Status{Colors.ENDC}")
    print("=" * 50)
    
    # Check Azure credentials
    print(f"\n{Colors.CYAN}Azure AD:{Colors.ENDC}")
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET")
    
    if all([tenant_id, client_id, client_secret]):
        print(f"  {Colors.GREEN}✓{Colors.ENDC} Credentials configured")
        print(f"    Tenant ID: {tenant_id[:8]}...")
        print(f"    Client ID: {client_id[:8]}...")
    else:
        print(f"  {Colors.RED}✗{Colors.ENDC} Missing credentials")
        if not tenant_id:
            print(f"    Missing: AZURE_TENANT_ID")
        if not client_id:
            print(f"    Missing: AZURE_CLIENT_ID")
        if not client_secret:
            print(f"    Missing: AZURE_CLIENT_SECRET")
    
    # Check GitHub credentials
    print(f"\n{Colors.CYAN}GitHub:{Colors.ENDC}")
    ghe_token = os.environ.get("GHE_ADMIN_TOKEN") or os.environ.get("beast")
    
    if ghe_token:
        print(f"  {Colors.GREEN}✓{Colors.ENDC} Token configured")
        print(f"    Token: {ghe_token[:8]}...")
    else:
        print(f"  {Colors.RED}✗{Colors.ENDC} Missing token (GHE_ADMIN_TOKEN or beast)")


def main():
    parser = argparse.ArgumentParser(
        description='God Mode - Rapid Azure AD & GitHub Enterprise Bulk Provisioning',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Provision 3 orgs with 50 users each
  python god_mode.py provision --orgs 3 --users 50

  # Provision from YAML config
  python god_mode.py provision --config infrastructure.yaml

  # Generate sample config
  python god_mode.py generate-config --output my-infra.yaml

  # Check status
  python god_mode.py status
"""
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Provision command
    provision_parser = subparsers.add_parser('provision', help='Provision infrastructure')
    provision_parser.add_argument('--config', help='YAML configuration file')
    provision_parser.add_argument('--tenants', type=int, help='Number of tenants (requires Azure subscription)')
    provision_parser.add_argument('--orgs', type=int, help='Number of organizations/groups')
    provision_parser.add_argument('--users', type=int, help='Number of users per organization')
    provision_parser.add_argument('--github', action='store_true', help='Also provision GitHub resources')
    provision_parser.set_defaults(func=cmd_provision)
    
    # Generate config command
    gen_parser = subparsers.add_parser('generate-config', help='Generate sample config')
    gen_parser.add_argument('--output', help='Output file path')
    gen_parser.set_defaults(func=cmd_generate_config)
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Check status')
    status_parser.set_defaults(func=cmd_status)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
    else:
        args.func(args)


if __name__ == '__main__':
    main()
