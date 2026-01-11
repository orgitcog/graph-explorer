#!/usr/bin/env python3
"""
Rapid Provision - One-liner bulk provisioning for Azure AD and GitHub

Deploy 3 tenants, 9 orgs, 50 users in a single command:
    python rapid_provision.py --tenants 3 --orgs 9 --users 50

This is the "beast mode" equivalent for Azure AD - matching the speed
and simplicity of GitHub Enterprise org/repo creation.
"""

import os
import sys
import json
import asyncio
import aiohttp
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import secrets
import string

# Configuration
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
GITHUB_API = "https://api.github.com"

# Colors
class C:
    H = '\033[95m'  # Header
    B = '\033[94m'  # Blue
    C = '\033[96m'  # Cyan
    G = '\033[92m'  # Green
    Y = '\033[93m'  # Yellow
    R = '\033[91m'  # Red
    E = '\033[0m'   # End
    BOLD = '\033[1m'


@dataclass
class Stats:
    """Provisioning statistics"""
    groups_created: int = 0
    groups_failed: int = 0
    users_created: int = 0
    users_failed: int = 0
    repos_created: int = 0
    repos_failed: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    
    @property
    def duration(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()
    
    @property
    def total_created(self) -> int:
        return self.groups_created + self.users_created + self.repos_created
    
    @property
    def total_failed(self) -> int:
        return self.groups_failed + self.users_failed + self.repos_failed


class RapidProvisioner:
    """Ultra-fast bulk provisioning engine"""
    
    def __init__(self, concurrency: int = 20):
        self.tenant_id = os.environ.get("AZURE_TENANT_ID")
        self.client_id = os.environ.get("AZURE_CLIENT_ID")
        self.client_secret = os.environ.get("AZURE_CLIENT_SECRET")
        self.github_token = os.environ.get("beast") or os.environ.get("GHE_ADMIN_TOKEN")
        
        self._token = None
        self._session = None
        self.concurrency = concurrency
        self.stats = Stats()
        self.results = {"groups": [], "users": [], "repos": []}
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()
    
    async def get_token(self) -> str:
        """Get Graph API token"""
        if self._token:
            return self._token
        
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        
        async with self._session.post(url, data=data) as r:
            result = await r.json()
            self._token = result.get("access_token")
            return self._token
    
    async def graph(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make Graph API request"""
        token = await self.get_token()
        url = f"{GRAPH_ENDPOINT}{endpoint}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        
        async with self._session.request(method, url, headers=headers, json=data) as r:
            if r.status == 204:
                return {}
            return await r.json()
    
    async def github(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make GitHub API request"""
        url = f"{GITHUB_API}{endpoint}"
        headers = {"Authorization": f"token {self.github_token}", "Accept": "application/vnd.github.v3+json"}
        
        async with self._session.request(method, url, headers=headers, json=data) as r:
            if r.status == 204:
                return {}
            return await r.json()
    
    def gen_password(self) -> str:
        """Generate secure password"""
        chars = string.ascii_letters + string.digits + "!@#$%"
        return ''.join(secrets.choice(chars) for _ in range(16))
    
    async def create_group(self, name: str, desc: str = "") -> bool:
        """Create a single group"""
        try:
            result = await self.graph("POST", "/groups", {
                "displayName": name,
                "description": desc or f"Auto-provisioned: {name}",
                "mailEnabled": False,
                "mailNickname": name.lower().replace(" ", "").replace("-", ""),
                "securityEnabled": True
            })
            
            if "id" in result:
                self.stats.groups_created += 1
                self.results["groups"].append({"name": name, "id": result["id"]})
                return True
            else:
                self.stats.groups_failed += 1
                return False
        except:
            self.stats.groups_failed += 1
            return False
    
    async def create_user(self, name: str, username: str, dept: str = "", title: str = "") -> bool:
        """Create a single user"""
        try:
            password = self.gen_password()
            result = await self.graph("POST", "/users", {
                "accountEnabled": True,
                "displayName": name,
                "mailNickname": username,
                "userPrincipalName": f"{username}@{self.tenant_id}.onmicrosoft.com",
                "department": dept,
                "jobTitle": title,
                "passwordProfile": {
                    "forceChangePasswordNextSignIn": True,
                    "password": password
                }
            })
            
            if "id" in result:
                self.stats.users_created += 1
                self.results["users"].append({
                    "name": name,
                    "id": result["id"],
                    "upn": result.get("userPrincipalName"),
                    "password": password
                })
                return True
            else:
                self.stats.users_failed += 1
                return False
        except:
            self.stats.users_failed += 1
            return False
    
    async def create_repo(self, org: str, name: str, desc: str = "") -> bool:
        """Create a GitHub repo"""
        try:
            result = await self.github("POST", f"/orgs/{org}/repos", {
                "name": name,
                "description": desc or f"Auto-provisioned: {name}",
                "private": False,
                "auto_init": True
            })
            
            if "id" in result:
                self.stats.repos_created += 1
                self.results["repos"].append({
                    "name": result.get("full_name"),
                    "url": result.get("html_url")
                })
                return True
            else:
                self.stats.repos_failed += 1
                return False
        except:
            self.stats.repos_failed += 1
            return False
    
    async def provision(self, orgs: int = 3, users_per_org: int = 10, github_org: str = None, repos_per_org: int = 0):
        """
        Rapid bulk provisioning
        
        Args:
            orgs: Number of Azure AD groups/organizations to create
            users_per_org: Number of users per organization
            github_org: GitHub organization to create repos in (optional)
            repos_per_org: Number of repos per org (optional)
        """
        self.stats = Stats()
        total = orgs + (orgs * users_per_org) + (orgs * repos_per_org if github_org else 0)
        
        print(f"\n{C.BOLD}{C.C}╔══════════════════════════════════════════════════════════════════╗{C.E}")
        print(f"{C.BOLD}{C.C}║  RAPID PROVISION - Beast Mode                                    ║{C.E}")
        print(f"{C.BOLD}{C.C}╚══════════════════════════════════════════════════════════════════╝{C.E}")
        
        print(f"\n{C.Y}Provisioning:{C.E}")
        print(f"  • {orgs} organizations/groups")
        print(f"  • {orgs * users_per_org} users ({users_per_org} per org)")
        if github_org and repos_per_org:
            print(f"  • {orgs * repos_per_org} GitHub repos ({repos_per_org} per org)")
        print(f"  • Concurrency: {self.concurrency}")
        print()
        
        semaphore = asyncio.Semaphore(self.concurrency)
        
        async def with_sem(coro):
            async with semaphore:
                return await coro
        
        # Create groups
        print(f"{C.Y}Creating groups...{C.E}", end=" ", flush=True)
        group_tasks = []
        for i in range(orgs):
            name = f"Org-{i+1:03d}"
            group_tasks.append(with_sem(self.create_group(name)))
        
        await asyncio.gather(*group_tasks)
        print(f"{C.G}✓ {self.stats.groups_created}/{orgs}{C.E}")
        
        # Create users
        print(f"{C.Y}Creating users...{C.E}", end=" ", flush=True)
        user_tasks = []
        titles = ["Developer", "Manager", "Analyst", "Engineer", "Designer", "Lead", "Architect", "Admin", "Support", "QA"]
        
        for i in range(orgs):
            org_name = f"Org-{i+1:03d}"
            for j in range(users_per_org):
                user_num = i * users_per_org + j + 1
                name = f"User {user_num:04d}"
                username = f"user{user_num:04d}"
                title = titles[j % len(titles)]
                user_tasks.append(with_sem(self.create_user(name, username, org_name, title)))
        
        await asyncio.gather(*user_tasks)
        print(f"{C.G}✓ {self.stats.users_created}/{orgs * users_per_org}{C.E}")
        
        # Create repos
        if github_org and repos_per_org:
            print(f"{C.Y}Creating repos...{C.E}", end=" ", flush=True)
            repo_tasks = []
            
            for i in range(orgs):
                for j in range(repos_per_org):
                    name = f"org{i+1:02d}-repo{j+1:02d}"
                    repo_tasks.append(with_sem(self.create_repo(github_org, name)))
            
            await asyncio.gather(*repo_tasks)
            print(f"{C.G}✓ {self.stats.repos_created}/{orgs * repos_per_org}{C.E}")
        
        # Summary
        print(f"\n{C.BOLD}═══════════════════════════════════════════════════════════════════{C.E}")
        print(f"{C.G}Provisioning Complete!{C.E}")
        print(f"Duration: {C.C}{self.stats.duration:.2f}s{C.E}")
        print(f"Rate: {C.C}{self.stats.total_created / self.stats.duration:.1f} resources/sec{C.E}")
        print()
        print(f"  Groups: {C.G}{self.stats.groups_created}{C.E} created" + (f", {C.R}{self.stats.groups_failed}{C.E} failed" if self.stats.groups_failed else ""))
        print(f"  Users:  {C.G}{self.stats.users_created}{C.E} created" + (f", {C.R}{self.stats.users_failed}{C.E} failed" if self.stats.users_failed else ""))
        if github_org and repos_per_org:
            print(f"  Repos:  {C.G}{self.stats.repos_created}{C.E} created" + (f", {C.R}{self.stats.repos_failed}{C.E} failed" if self.stats.repos_failed else ""))
        
        # Save results
        output_dir = Path.home() / ".godmode"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"rapid_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(output_file, 'w') as f:
            json.dump({
                "stats": {
                    "groups_created": self.stats.groups_created,
                    "users_created": self.stats.users_created,
                    "repos_created": self.stats.repos_created,
                    "duration_seconds": self.stats.duration
                },
                "results": self.results
            }, f, indent=2)
        
        print(f"\n{C.B}Results saved to: {output_file}{C.E}")
        
        return self.results


async def main():
    parser = argparse.ArgumentParser(
        description="Rapid Provision - One-liner bulk provisioning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create 3 orgs with 10 users each (30 users total)
  python rapid_provision.py --orgs 3 --users 10

  # Create 9 orgs with 50 users each (450 users total)
  python rapid_provision.py --orgs 9 --users 50

  # Include GitHub repos
  python rapid_provision.py --orgs 3 --users 10 --github-org orgitcog --repos 3

  # Maximum speed (high concurrency)
  python rapid_provision.py --orgs 9 --users 50 --concurrency 50
"""
    )
    
    parser.add_argument("--orgs", type=int, default=3, help="Number of organizations/groups (default: 3)")
    parser.add_argument("--users", type=int, default=10, help="Users per organization (default: 10)")
    parser.add_argument("--github-org", type=str, help="GitHub organization for repos (optional)")
    parser.add_argument("--repos", type=int, default=0, help="Repos per org (default: 0)")
    parser.add_argument("--concurrency", type=int, default=20, help="Concurrent API calls (default: 20)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without creating")
    
    args = parser.parse_args()
    
    if args.dry_run:
        print(f"\n{C.Y}DRY RUN - Would create:{C.E}")
        print(f"  • {args.orgs} organizations/groups")
        print(f"  • {args.orgs * args.users} users")
        if args.github_org and args.repos:
            print(f"  • {args.orgs * args.repos} GitHub repos in {args.github_org}")
        return
    
    # Check credentials
    if not all([os.environ.get("AZURE_TENANT_ID"), os.environ.get("AZURE_CLIENT_ID"), os.environ.get("AZURE_CLIENT_SECRET")]):
        print(f"{C.R}Error: Missing Azure credentials{C.E}")
        print("Set: AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET")
        sys.exit(1)
    
    async with RapidProvisioner(concurrency=args.concurrency) as provisioner:
        await provisioner.provision(
            orgs=args.orgs,
            users_per_org=args.users,
            github_org=args.github_org,
            repos_per_org=args.repos
        )


if __name__ == "__main__":
    asyncio.run(main())
