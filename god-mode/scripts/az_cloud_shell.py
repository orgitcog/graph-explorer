#!/usr/bin/env python3
"""
Azure Cloud Shell Integration for Graph Explorer

Provides Azure Cloud Shell-like functionality that can be embedded
in the Graph Explorer interface or used standalone.

Features:
- Azure AD authentication
- Resource management
- Graph API access
- PowerShell-like command interface
- Integration with God Mode provisioning
"""

import os
import sys
import json
import asyncio
import aiohttp
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import readline
import shlex

try:
    from rich.console import Console
    from rich.table import Table
    from rich.syntax import Syntax
    from rich.panel import Panel
    from rich.markdown import Markdown
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# Configuration
CONFIG_DIR = Path.home() / ".azshell"
HISTORY_FILE = CONFIG_DIR / "history"

# ANSI colors
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

console = Console() if HAS_RICH else None


class AzureCloudShell:
    """
    Azure Cloud Shell emulator with Graph API integration
    """
    
    def __init__(self):
        self.tenant_id = os.environ.get("AZURE_TENANT_ID")
        self.client_id = os.environ.get("AZURE_CLIENT_ID")
        self.client_secret = os.environ.get("AZURE_CLIENT_SECRET")
        self.subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID")
        
        self._graph_token = None
        self._mgmt_token = None
        self._session = None
        
        self.current_subscription = self.subscription_id
        self.output_format = "table"  # table, json, yaml
        
        # Command registry
        self.commands = {
            "help": self.cmd_help,
            "login": self.cmd_login,
            "account": self.cmd_account,
            "ad": self.cmd_ad,
            "group": self.cmd_group,
            "user": self.cmd_user,
            "app": self.cmd_app,
            "graph": self.cmd_graph,
            "godmode": self.cmd_godmode,
            "clear": self.cmd_clear,
            "exit": self.cmd_exit,
            "set": self.cmd_set,
        }
    
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
                raise Exception(f"Token acquisition failed: {response.status}")
    
    async def get_graph_token(self) -> str:
        """Get Microsoft Graph token"""
        if not self._graph_token:
            self._graph_token = await self._get_token("https://graph.microsoft.com")
        return self._graph_token
    
    async def graph_request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make a Graph API request"""
        token = await self.get_graph_token()
        url = f"https://graph.microsoft.com/v1.0{endpoint}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with self._session.request(method, url, headers=headers, json=data) as response:
            if response.status == 204:
                return {}
            return await response.json()
    
    def print_output(self, data: Any, title: str = None):
        """Print output in the configured format"""
        if self.output_format == "json":
            print(json.dumps(data, indent=2))
        elif HAS_RICH and self.output_format == "table" and isinstance(data, list):
            if not data:
                print("No results found.")
                return
            
            table = Table(title=title)
            
            # Get columns from first item
            if isinstance(data[0], dict):
                for key in data[0].keys():
                    table.add_column(key)
                
                for item in data:
                    table.add_row(*[str(v)[:50] for v in item.values()])
            
            console.print(table)
        else:
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            print(f"  {k}: {v}")
                        print()
                    else:
                        print(f"  {item}")
            elif isinstance(data, dict):
                for k, v in data.items():
                    print(f"  {k}: {v}")
            else:
                print(data)
    
    # ==================== COMMANDS ====================
    
    async def cmd_help(self, args: List[str]):
        """Show help"""
        help_text = """
Azure Cloud Shell (Graph Explorer Integration)

Commands:
  login                    Test authentication
  account show             Show account information
  
  ad user list             List Azure AD users
  ad user show <id>        Show user details
  ad user create           Create a new user (interactive)
  
  ad group list            List Azure AD groups
  ad group show <id>       Show group details
  ad group create          Create a new group (interactive)
  
  ad app list              List applications
  ad app show <id>         Show application details
  
  graph GET <endpoint>     Make a Graph API GET request
  graph POST <endpoint>    Make a Graph API POST request
  
  godmode provision        Run God Mode bulk provisioning
  godmode status           Check God Mode status
  
  set output <format>      Set output format (table, json)
  clear                    Clear screen
  exit                     Exit the shell
"""
        print(help_text)
    
    async def cmd_login(self, args: List[str]):
        """Test authentication"""
        print(f"\n{Colors.CYAN}Testing authentication...{Colors.ENDC}")
        
        try:
            token = await self.get_graph_token()
            org = await self.graph_request("GET", "/organization")
            
            if org.get("value"):
                org_info = org["value"][0]
                print(f"{Colors.GREEN}✓ Authenticated{Colors.ENDC}")
                print(f"  Organization: {org_info.get('displayName', 'N/A')}")
                print(f"  Tenant ID: {org_info.get('id', 'N/A')}")
            else:
                print(f"{Colors.GREEN}✓ Authenticated{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.RED}✗ Authentication failed: {e}{Colors.ENDC}")
    
    async def cmd_account(self, args: List[str]):
        """Account operations"""
        if not args or args[0] == "show":
            try:
                org = await self.graph_request("GET", "/organization")
                
                if org.get("value"):
                    org_info = org["value"][0]
                    print(f"\n{Colors.BOLD}Account Information{Colors.ENDC}")
                    print(f"  Display Name: {org_info.get('displayName', 'N/A')}")
                    print(f"  Tenant ID: {org_info.get('id', 'N/A')}")
                    print(f"  Tenant Type: {org_info.get('tenantType', 'N/A')}")
                    
                    domains = org_info.get('verifiedDomains', [])
                    if domains:
                        print(f"  Domains:")
                        for d in domains:
                            default = " (default)" if d.get('isDefault') else ""
                            print(f"    - {d.get('name')}{default}")
            except Exception as e:
                print(f"{Colors.RED}Error: {e}{Colors.ENDC}")
    
    async def cmd_ad(self, args: List[str]):
        """Azure AD operations"""
        if not args:
            print("Usage: ad <user|group|app> <command>")
            return
        
        resource = args[0]
        subargs = args[1:] if len(args) > 1 else []
        
        if resource == "user":
            await self.cmd_user(subargs)
        elif resource == "group":
            await self.cmd_group(subargs)
        elif resource == "app":
            await self.cmd_app(subargs)
        else:
            print(f"Unknown resource: {resource}")
    
    async def cmd_user(self, args: List[str]):
        """User operations"""
        if not args or args[0] == "list":
            top = 20
            if len(args) > 1 and args[1] == "--top":
                top = int(args[2]) if len(args) > 2 else 20
            
            result = await self.graph_request("GET", f"/users?$top={top}&$select=id,displayName,userPrincipalName,jobTitle")
            users = result.get("value", [])
            
            self.print_output(users, "Users")
        
        elif args[0] == "show" and len(args) > 1:
            user_id = args[1]
            result = await self.graph_request("GET", f"/users/{user_id}")
            self.print_output(result)
        
        elif args[0] == "create":
            print("Creating new user...")
            display_name = input("Display Name: ")
            username = input("Username: ")
            
            import secrets
            import string
            password = ''.join(secrets.choice(string.ascii_letters + string.digits + "!@#$%") for _ in range(16))
            
            user_data = {
                "accountEnabled": True,
                "displayName": display_name,
                "mailNickname": username,
                "userPrincipalName": f"{username}@{self.tenant_id}.onmicrosoft.com",
                "passwordProfile": {
                    "forceChangePasswordNextSignIn": True,
                    "password": password
                }
            }
            
            try:
                result = await self.graph_request("POST", "/users", user_data)
                print(f"{Colors.GREEN}✓ User created{Colors.ENDC}")
                print(f"  ID: {result.get('id')}")
                print(f"  UPN: {result.get('userPrincipalName')}")
                print(f"  Temp Password: {password}")
            except Exception as e:
                print(f"{Colors.RED}✗ Failed: {e}{Colors.ENDC}")
    
    async def cmd_group(self, args: List[str]):
        """Group operations"""
        if not args or args[0] == "list":
            top = 20
            result = await self.graph_request("GET", f"/groups?$top={top}&$select=id,displayName,description,groupTypes")
            groups = result.get("value", [])
            
            self.print_output(groups, "Groups")
        
        elif args[0] == "show" and len(args) > 1:
            group_id = args[1]
            result = await self.graph_request("GET", f"/groups/{group_id}")
            self.print_output(result)
        
        elif args[0] == "create":
            print("Creating new group...")
            display_name = input("Display Name: ")
            description = input("Description: ")
            
            group_data = {
                "displayName": display_name,
                "description": description,
                "mailEnabled": False,
                "mailNickname": display_name.lower().replace(" ", ""),
                "securityEnabled": True
            }
            
            try:
                result = await self.graph_request("POST", "/groups", group_data)
                print(f"{Colors.GREEN}✓ Group created{Colors.ENDC}")
                print(f"  ID: {result.get('id')}")
                print(f"  Name: {result.get('displayName')}")
            except Exception as e:
                print(f"{Colors.RED}✗ Failed: {e}{Colors.ENDC}")
    
    async def cmd_app(self, args: List[str]):
        """Application operations"""
        if not args or args[0] == "list":
            result = await self.graph_request("GET", "/applications?$top=20&$select=id,displayName,appId,createdDateTime")
            apps = result.get("value", [])
            
            self.print_output(apps, "Applications")
        
        elif args[0] == "show" and len(args) > 1:
            app_id = args[1]
            result = await self.graph_request("GET", f"/applications/{app_id}")
            self.print_output(result)
    
    async def cmd_graph(self, args: List[str]):
        """Direct Graph API calls"""
        if len(args) < 2:
            print("Usage: graph <GET|POST|PATCH|DELETE> <endpoint>")
            return
        
        method = args[0].upper()
        endpoint = args[1]
        
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        
        try:
            if method == "GET":
                result = await self.graph_request("GET", endpoint)
            elif method == "POST":
                body_str = input("JSON Body (or empty): ")
                body = json.loads(body_str) if body_str else None
                result = await self.graph_request("POST", endpoint, body)
            elif method == "PATCH":
                body_str = input("JSON Body: ")
                body = json.loads(body_str)
                result = await self.graph_request("PATCH", endpoint, body)
            elif method == "DELETE":
                result = await self.graph_request("DELETE", endpoint)
            else:
                print(f"Unsupported method: {method}")
                return
            
            self.print_output(result)
        except Exception as e:
            print(f"{Colors.RED}Error: {e}{Colors.ENDC}")
    
    async def cmd_godmode(self, args: List[str]):
        """God Mode operations"""
        if not args or args[0] == "status":
            print(f"\n{Colors.BOLD}God Mode Status{Colors.ENDC}")
            print(f"  Azure Tenant: {self.tenant_id[:8] if self.tenant_id else 'Not set'}...")
            print(f"  Client ID: {self.client_id[:8] if self.client_id else 'Not set'}...")
            print(f"  Credentials: {'✓ Configured' if all([self.tenant_id, self.client_id, self.client_secret]) else '✗ Missing'}")
        
        elif args[0] == "provision":
            orgs = 3
            users = 10
            
            if "--orgs" in args:
                idx = args.index("--orgs")
                orgs = int(args[idx + 1]) if len(args) > idx + 1 else 3
            
            if "--users" in args:
                idx = args.index("--users")
                users = int(args[idx + 1]) if len(args) > idx + 1 else 10
            
            print(f"\n{Colors.BOLD}God Mode Provisioning{Colors.ENDC}")
            print(f"  Organizations: {orgs}")
            print(f"  Users per org: {users}")
            print(f"  Total users: {orgs * users}")
            
            confirm = input("\nProceed? (y/n): ")
            if confirm.lower() != 'y':
                print("Cancelled.")
                return
            
            # Import and run god_mode
            try:
                from god_mode import generate_infrastructure_spec, run_provisioning
                spec = generate_infrastructure_spec(orgs=orgs, users_per_org=users)
                await run_provisioning(spec)
            except ImportError:
                print("Running inline provisioning...")
                # Inline provisioning
                for i in range(orgs):
                    org_name = f"Organization-{i+1:02d}"
                    print(f"  Creating group: {org_name}")
                    
                    try:
                        await self.graph_request("POST", "/groups", {
                            "displayName": org_name,
                            "mailEnabled": False,
                            "mailNickname": f"org{i+1:02d}",
                            "securityEnabled": True
                        })
                    except:
                        pass
                    
                    for j in range(users):
                        user_num = i * users + j + 1
                        print(f"    Creating user: User {user_num:03d}")
                        
                        import secrets
                        import string
                        password = ''.join(secrets.choice(string.ascii_letters + string.digits + "!@#$%") for _ in range(16))
                        
                        try:
                            await self.graph_request("POST", "/users", {
                                "accountEnabled": True,
                                "displayName": f"User {user_num:03d}",
                                "mailNickname": f"user{user_num:03d}",
                                "userPrincipalName": f"user{user_num:03d}@{self.tenant_id}.onmicrosoft.com",
                                "passwordProfile": {
                                    "forceChangePasswordNextSignIn": True,
                                    "password": password
                                }
                            })
                        except:
                            pass
                
                print(f"\n{Colors.GREEN}✓ Provisioning complete{Colors.ENDC}")
    
    async def cmd_set(self, args: List[str]):
        """Set configuration"""
        if len(args) < 2:
            print("Usage: set <option> <value>")
            print("Options: output (table, json)")
            return
        
        option = args[0]
        value = args[1]
        
        if option == "output":
            if value in ["table", "json"]:
                self.output_format = value
                print(f"Output format set to: {value}")
            else:
                print(f"Invalid output format: {value}")
    
    async def cmd_clear(self, args: List[str]):
        """Clear screen"""
        os.system('clear')
    
    async def cmd_exit(self, args: List[str]):
        """Exit the shell"""
        raise SystemExit()
    
    async def run_command(self, command_line: str):
        """Parse and run a command"""
        try:
            parts = shlex.split(command_line)
        except ValueError:
            parts = command_line.split()
        
        if not parts:
            return
        
        cmd = parts[0].lower()
        args = parts[1:]
        
        if cmd in self.commands:
            await self.commands[cmd](args)
        else:
            print(f"Unknown command: {cmd}")
            print("Type 'help' for available commands")
    
    async def run_interactive(self):
        """Run interactive shell"""
        print(f"""
{Colors.BLUE}╔══════════════════════════════════════════════════════════════════╗
║  {Colors.BOLD}Azure Cloud Shell{Colors.BLUE}                                               ║
║  {Colors.DIM}Graph Explorer Integration{Colors.BLUE}                                      ║
╚══════════════════════════════════════════════════════════════════╝{Colors.ENDC}

Type 'help' for commands, 'exit' to quit.
""")
        
        # Try to authenticate on startup
        try:
            await self.get_graph_token()
            org = await self.graph_request("GET", "/organization")
            if org.get("value"):
                print(f"{Colors.GREEN}Connected to: {org['value'][0].get('displayName', 'Unknown')}{Colors.ENDC}\n")
        except:
            print(f"{Colors.YELLOW}Not authenticated. Run 'login' to authenticate.{Colors.ENDC}\n")
        
        # Setup readline history
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if HISTORY_FILE.exists():
            readline.read_history_file(str(HISTORY_FILE))
        
        while True:
            try:
                command = input(f"{Colors.CYAN}az>{Colors.ENDC} ").strip()
                
                if command:
                    readline.write_history_file(str(HISTORY_FILE))
                    await self.run_command(command)
                    
            except KeyboardInterrupt:
                print("\nUse 'exit' to quit")
            except SystemExit:
                print("Goodbye!")
                break
            except EOFError:
                break
            except Exception as e:
                print(f"{Colors.RED}Error: {e}{Colors.ENDC}")


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Azure Cloud Shell Integration")
    parser.add_argument("command", nargs="*", help="Command to run (or empty for interactive)")
    
    args = parser.parse_args()
    
    async with AzureCloudShell() as shell:
        if args.command:
            await shell.run_command(" ".join(args.command))
        else:
            await shell.run_interactive()


if __name__ == "__main__":
    asyncio.run(main())
