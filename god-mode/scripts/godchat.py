#!/usr/bin/env python3
"""
GodChat - AI-Powered Shell for God Mode

An aichat-inspired CLI tool for God Mode that integrates:
- Local LLM support (llama.cpp)
- Cloud LLM fallback (OpenAI, Claude, etc.)
- God Mode provisioning commands
- Shell assistant for Azure/GitHub operations
- Interactive REPL with history and completion

Usage:
    godchat                    # Start REPL mode
    godchat "create 10 users"  # CMD mode - one-shot query
    cat users.csv | godchat    # Pipe mode
    godchat -f config.yaml     # File input mode
"""

import os
import sys
import json
import asyncio
import aiohttp
import readline
import atexit
import signal
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
import argparse
import subprocess
import re

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Config:
    """GodChat configuration"""
    # LLM Settings
    local_endpoint: str = "http://127.0.0.1:8080"
    openai_endpoint: str = "https://api.openai.com/v1"
    default_model: str = "local"  # local, gpt-4, claude-3, etc.
    
    # God Mode Settings
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    github_token: str = ""
    
    # UI Settings
    theme: str = "dark"
    prompt: str = "godchat> "
    history_file: str = str(Path.home() / ".godchat_history")
    max_history: int = 1000
    
    # System prompt for God Mode assistant
    system_prompt: str = """You are GodChat, an AI assistant for God Mode - a rapid provisioning system for Azure AD and GitHub Enterprise.

You can help with:
1. Azure AD operations: Create users, groups, applications, manage permissions
2. GitHub operations: Create repos, manage orgs, sync with Azure AD
3. Bulk provisioning: Create hundreds of resources in seconds
4. Shell commands: Generate and execute Azure CLI, GitHub CLI, and PowerShell commands

When the user asks to perform an action, respond with:
- A brief explanation of what you'll do
- The exact command(s) to execute (in ```bash or ```powershell blocks)
- Ask for confirmation before executing destructive operations

Available God Mode commands:
- .provision <count> - Bulk provision users/groups
- .sync - Sync Azure AD with GitHub
- .graph <endpoint> - Query Microsoft Graph API
- .github <command> - Execute GitHub CLI command
- .exec <command> - Execute shell command

Be concise, precise, and action-oriented."""

    @classmethod
    def load(cls) -> "Config":
        """Load config from environment and file"""
        config = cls()
        
        # Load from environment
        config.azure_tenant_id = os.environ.get("AZURE_TENANT_ID", "")
        config.azure_client_id = os.environ.get("AZURE_CLIENT_ID", "")
        config.azure_client_secret = os.environ.get("AZURE_CLIENT_SECRET", "")
        config.github_token = os.environ.get("beast") or os.environ.get("GHE_ADMIN_TOKEN", "")
        
        # Load from config file if exists
        config_file = Path.home() / ".godchat.json"
        if config_file.exists():
            with open(config_file) as f:
                data = json.load(f)
                for key, value in data.items():
                    if hasattr(config, key):
                        setattr(config, key, value)
        
        return config


# ═══════════════════════════════════════════════════════════════════════════════
# COLORS AND UI
# ═══════════════════════════════════════════════════════════════════════════════

class Colors:
    """Terminal colors for dark theme"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # Dark theme colors
    PRIMARY = "\033[38;5;39m"      # Bright blue
    SECONDARY = "\033[38;5;245m"   # Gray
    SUCCESS = "\033[38;5;82m"      # Green
    WARNING = "\033[38;5;214m"     # Orange
    ERROR = "\033[38;5;196m"       # Red
    INFO = "\033[38;5;147m"        # Light purple
    CODE = "\033[38;5;229m"        # Yellow
    
    # Prompt colors
    PROMPT = "\033[38;5;39m"       # Blue
    INPUT = "\033[38;5;255m"       # White


def styled(text: str, *styles: str) -> str:
    """Apply styles to text"""
    return "".join(styles) + text + Colors.RESET


def print_banner():
    """Print GodChat banner"""
    banner = f"""
{Colors.PRIMARY}{Colors.BOLD}╔══════════════════════════════════════════════════════════════════╗
║   ▄████  ▒█████  ▓█████▄  ▄████▄   ██░ ██  ▄▄▄     ▄▄▄█████▓   ║
║  ██▒ ▀█▒▒██▒  ██▒▒██▀ ██▌▒██▀ ▀█  ▓██░ ██▒▒████▄   ▓  ██▒ ▓▒   ║
║ ▒██░▄▄▄░▒██░  ██▒░██   █▌▒▓█    ▄ ▒██▀▀██░▒██  ▀█▄ ▒ ▓██░ ▒░   ║
║ ░▓█  ██▓▒██   ██░░▓█▄   ▌▒▓▓▄ ▄██▒░▓█ ░██ ░██▄▄▄▄██░ ▓██▓ ░    ║
║ ░▒▓███▀▒░ ████▓▒░░▒████▓ ▒ ▓███▀ ░░▓█▒░██▓ ▓█   ▓██▒ ▒██▒ ░    ║
║  ░▒   ▒ ░ ▒░▒░▒░  ▒▒▓  ▒ ░ ░▒ ▒  ░ ▒ ░░▒░▒ ▒▒   ▓▒█░ ▒ ░░      ║
║   ░   ░   ░ ▒ ▒░  ░ ▒  ▒   ░  ▒    ▒ ░▒░ ░  ▒   ▒▒ ░   ░       ║
║ ░ ░   ░ ░ ░ ░ ▒   ░ ░  ░ ░         ░  ░░ ░  ░   ▒    ░         ║
║       ░     ░ ░     ░    ░ ░       ░  ░  ░      ░  ░            ║
╚══════════════════════════════════════════════════════════════════╝{Colors.RESET}
{Colors.SECONDARY}AI-Powered Shell for God Mode • Local LLM + Cloud Fallback{Colors.RESET}
{Colors.DIM}Type .help for commands, .quit to exit{Colors.RESET}
"""
    print(banner)


# ═══════════════════════════════════════════════════════════════════════════════
# LLM CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

class LLMClient:
    """Unified LLM client supporting local and cloud models"""
    
    def __init__(self, config: Config):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self.conversation: List[Dict[str, str]] = []
        self.local_available = False
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        await self._check_local()
        return self
    
    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()
    
    async def _check_local(self):
        """Check if local LLM server is available"""
        try:
            async with self._session.get(f"{self.config.local_endpoint}/health", timeout=aiohttp.ClientTimeout(total=2)) as r:
                self.local_available = r.status == 200
        except:
            self.local_available = False
    
    async def chat(self, message: str, stream: bool = True) -> str:
        """Send a chat message and get response"""
        self.conversation.append({"role": "user", "content": message})
        
        messages = [{"role": "system", "content": self.config.system_prompt}] + self.conversation
        
        # Try local first, then cloud
        if self.local_available and self.config.default_model == "local":
            response = await self._chat_local(messages, stream)
        else:
            response = await self._chat_cloud(messages, stream)
        
        self.conversation.append({"role": "assistant", "content": response})
        return response
    
    async def _chat_local(self, messages: List[Dict], stream: bool) -> str:
        """Chat with local llama.cpp server"""
        url = f"{self.config.local_endpoint}/v1/chat/completions"
        payload = {
            "messages": messages,
            "stream": stream,
            "max_tokens": 2048,
            "temperature": 0.7
        }
        
        try:
            if stream:
                return await self._stream_response(url, payload)
            else:
                async with self._session.post(url, json=payload) as r:
                    data = await r.json()
                    return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"{Colors.WARNING}Local LLM failed, falling back to cloud...{Colors.RESET}")
            self.local_available = False
            return await self._chat_cloud(messages, stream)
    
    async def _chat_cloud(self, messages: List[Dict], stream: bool) -> str:
        """Chat with cloud LLM (OpenAI-compatible)"""
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return "Error: No API key configured. Set OPENAI_API_KEY or start local LLM server."
        
        url = f"{self.config.openai_endpoint}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "model": "gpt-4.1-mini",
            "messages": messages,
            "stream": stream,
            "max_tokens": 2048,
            "temperature": 0.7
        }
        
        try:
            if stream:
                return await self._stream_response(url, payload, headers)
            else:
                async with self._session.post(url, json=payload, headers=headers) as r:
                    data = await r.json()
                    return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def _stream_response(self, url: str, payload: Dict, headers: Dict = None) -> str:
        """Stream response and print tokens as they arrive"""
        full_response = ""
        
        async with self._session.post(url, json=payload, headers=headers or {}) as r:
            async for line in r.content:
                line = line.decode().strip()
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        if "choices" in chunk and len(chunk["choices"]) > 0:
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                print(content, end="", flush=True)
                                full_response += content
                    except json.JSONDecodeError:
                        pass
        
        print()  # Newline after streaming
        return full_response
    
    def clear_history(self):
        """Clear conversation history"""
        self.conversation = []


# ═══════════════════════════════════════════════════════════════════════════════
# GOD MODE COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

class GodModeCommands:
    """Built-in God Mode commands"""
    
    def __init__(self, config: Config):
        self.config = config
        self._graph_token = None
    
    async def get_graph_token(self) -> str:
        """Get Microsoft Graph API token"""
        if self._graph_token:
            return self._graph_token
        
        url = f"https://login.microsoftonline.com/{self.config.azure_tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.config.azure_client_id,
            "client_secret": self.config.azure_client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as r:
                result = await r.json()
                self._graph_token = result.get("access_token")
                return self._graph_token
    
    async def graph_query(self, endpoint: str) -> Dict:
        """Query Microsoft Graph API"""
        token = await self.get_graph_token()
        url = f"https://graph.microsoft.com/v1.0{endpoint}"
        headers = {"Authorization": f"Bearer {token}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as r:
                return await r.json()
    
    async def provision(self, count: int, resource_type: str = "users") -> Dict:
        """Bulk provision resources"""
        print(f"{Colors.INFO}Provisioning {count} {resource_type}...{Colors.RESET}")
        
        # Import and use the rapid provisioner
        try:
            from rapid_provision import RapidProvisioner
            async with RapidProvisioner() as provisioner:
                if resource_type == "users":
                    await provisioner.provision(orgs=1, users_per_org=count)
                elif resource_type == "groups":
                    await provisioner.provision(orgs=count, users_per_org=0)
                return {"status": "success", "count": count}
        except ImportError:
            return {"status": "error", "message": "RapidProvisioner not available"}
    
    def exec_command(self, command: str) -> str:
        """Execute a shell command"""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60
            )
            return result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return "Command timed out"
        except Exception as e:
            return f"Error: {str(e)}"
    
    def github_command(self, command: str) -> str:
        """Execute a GitHub CLI command"""
        return self.exec_command(f"gh {command}")


# ═══════════════════════════════════════════════════════════════════════════════
# REPL
# ═══════════════════════════════════════════════════════════════════════════════

class GodChatREPL:
    """Interactive REPL for GodChat"""
    
    COMMANDS = {
        ".help": "Show this help message",
        ".quit": "Exit GodChat",
        ".clear": "Clear conversation history",
        ".history": "Show conversation history",
        ".model": "Show/set current model",
        ".local": "Check local LLM status",
        ".provision": "Bulk provision resources",
        ".graph": "Query Microsoft Graph API",
        ".github": "Execute GitHub CLI command",
        ".exec": "Execute shell command",
        ".role": "Set assistant role/persona",
    }
    
    def __init__(self, config: Config):
        self.config = config
        self.llm: Optional[LLMClient] = None
        self.commands = GodModeCommands(config)
        self.running = False
        
        # Setup readline
        self._setup_readline()
    
    def _setup_readline(self):
        """Setup readline for history and completion"""
        # History
        history_file = Path(self.config.history_file)
        if history_file.exists():
            readline.read_history_file(str(history_file))
        readline.set_history_length(self.config.max_history)
        atexit.register(readline.write_history_file, str(history_file))
        
        # Completion
        readline.set_completer(self._completer)
        readline.parse_and_bind("tab: complete")
    
    def _completer(self, text: str, state: int) -> Optional[str]:
        """Tab completion for commands"""
        options = [cmd for cmd in self.COMMANDS.keys() if cmd.startswith(text)]
        if state < len(options):
            return options[state]
        return None
    
    async def run(self):
        """Run the REPL"""
        print_banner()
        
        async with LLMClient(self.config) as llm:
            self.llm = llm
            
            # Show LLM status
            if llm.local_available:
                print(f"{Colors.SUCCESS}✓ Local LLM available{Colors.RESET}")
            else:
                print(f"{Colors.WARNING}⚠ Local LLM not available, using cloud{Colors.RESET}")
            print()
            
            self.running = True
            while self.running:
                try:
                    # Get input
                    prompt = f"{Colors.PROMPT}{self.config.prompt}{Colors.RESET}"
                    user_input = input(prompt).strip()
                    
                    if not user_input:
                        continue
                    
                    # Handle commands
                    if user_input.startswith("."):
                        await self._handle_command(user_input)
                    else:
                        # Chat with LLM
                        print(f"\n{Colors.INFO}Assistant:{Colors.RESET}")
                        response = await llm.chat(user_input)
                        
                        # Check for executable code blocks
                        await self._handle_code_blocks(response)
                        print()
                
                except KeyboardInterrupt:
                    print(f"\n{Colors.DIM}Use .quit to exit{Colors.RESET}")
                except EOFError:
                    break
    
    async def _handle_command(self, cmd: str):
        """Handle REPL commands"""
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if command == ".quit" or command == ".exit":
            self.running = False
            print(f"{Colors.DIM}Goodbye!{Colors.RESET}")
        
        elif command == ".help":
            print(f"\n{Colors.PRIMARY}Available Commands:{Colors.RESET}")
            for cmd, desc in self.COMMANDS.items():
                print(f"  {Colors.CODE}{cmd:12}{Colors.RESET} {desc}")
            print()
        
        elif command == ".clear":
            self.llm.clear_history()
            print(f"{Colors.SUCCESS}Conversation cleared{Colors.RESET}")
        
        elif command == ".history":
            if not self.llm.conversation:
                print(f"{Colors.DIM}No conversation history{Colors.RESET}")
            else:
                for msg in self.llm.conversation:
                    role = msg["role"].capitalize()
                    color = Colors.PRIMARY if role == "User" else Colors.INFO
                    print(f"{color}{role}:{Colors.RESET} {msg['content'][:100]}...")
        
        elif command == ".model":
            if args:
                self.config.default_model = args
                print(f"{Colors.SUCCESS}Model set to: {args}{Colors.RESET}")
            else:
                print(f"Current model: {Colors.CODE}{self.config.default_model}{Colors.RESET}")
                print(f"Local available: {Colors.CODE}{self.llm.local_available}{Colors.RESET}")
        
        elif command == ".local":
            await self.llm._check_local()
            if self.llm.local_available:
                print(f"{Colors.SUCCESS}✓ Local LLM is available{Colors.RESET}")
            else:
                print(f"{Colors.ERROR}✗ Local LLM is not available{Colors.RESET}")
        
        elif command == ".provision":
            if args:
                try:
                    count = int(args.split()[0])
                    resource_type = args.split()[1] if len(args.split()) > 1 else "users"
                    result = await self.commands.provision(count, resource_type)
                    print(json.dumps(result, indent=2))
                except ValueError:
                    print(f"{Colors.ERROR}Usage: .provision <count> [users|groups]{Colors.RESET}")
            else:
                print(f"{Colors.ERROR}Usage: .provision <count> [users|groups]{Colors.RESET}")
        
        elif command == ".graph":
            if args:
                result = await self.commands.graph_query(args)
                print(json.dumps(result, indent=2))
            else:
                print(f"{Colors.ERROR}Usage: .graph <endpoint>{Colors.RESET}")
                print(f"Example: .graph /me")
        
        elif command == ".github":
            if args:
                result = self.commands.github_command(args)
                print(result)
            else:
                print(f"{Colors.ERROR}Usage: .github <command>{Colors.RESET}")
                print(f"Example: .github repo list")
        
        elif command == ".exec":
            if args:
                print(f"{Colors.WARNING}Executing: {args}{Colors.RESET}")
                result = self.commands.exec_command(args)
                print(result)
            else:
                print(f"{Colors.ERROR}Usage: .exec <command>{Colors.RESET}")
        
        elif command == ".role":
            if args:
                self.config.system_prompt = args
                self.llm.clear_history()
                print(f"{Colors.SUCCESS}Role updated{Colors.RESET}")
            else:
                print(f"Current role:\n{Colors.DIM}{self.config.system_prompt[:200]}...{Colors.RESET}")
        
        else:
            print(f"{Colors.ERROR}Unknown command: {command}{Colors.RESET}")
            print(f"Type .help for available commands")
    
    async def _handle_code_blocks(self, response: str):
        """Extract and optionally execute code blocks from response"""
        # Find code blocks
        pattern = r"```(bash|powershell|sh)\n(.*?)```"
        matches = re.findall(pattern, response, re.DOTALL)
        
        if matches:
            print(f"\n{Colors.WARNING}Found {len(matches)} executable code block(s){Colors.RESET}")
            for i, (lang, code) in enumerate(matches):
                print(f"\n{Colors.CODE}[{i+1}] {lang}:{Colors.RESET}")
                print(f"{Colors.DIM}{code.strip()}{Colors.RESET}")
            
            # Ask for confirmation
            try:
                confirm = input(f"\n{Colors.WARNING}Execute? [y/N/number]: {Colors.RESET}").strip().lower()
                if confirm == "y":
                    for lang, code in matches:
                        print(f"\n{Colors.INFO}Executing...{Colors.RESET}")
                        result = self.commands.exec_command(code.strip())
                        print(result)
                elif confirm.isdigit():
                    idx = int(confirm) - 1
                    if 0 <= idx < len(matches):
                        lang, code = matches[idx]
                        print(f"\n{Colors.INFO}Executing...{Colors.RESET}")
                        result = self.commands.exec_command(code.strip())
                        print(result)
            except (KeyboardInterrupt, EOFError):
                print(f"\n{Colors.DIM}Skipped{Colors.RESET}")


# ═══════════════════════════════════════════════════════════════════════════════
# CMD MODE
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_mode(query: str, config: Config, files: List[str] = None):
    """One-shot command mode"""
    # Build context from files
    context = ""
    if files:
        for f in files:
            path = Path(f)
            if path.exists():
                context += f"\n--- {f} ---\n{path.read_text()}\n"
    
    # Check for stdin
    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read()
        if stdin_content:
            context += f"\n--- stdin ---\n{stdin_content}\n"
    
    # Combine context and query
    if context:
        full_query = f"Context:\n{context}\n\nQuery: {query}"
    else:
        full_query = query
    
    async with LLMClient(config) as llm:
        print(f"{Colors.INFO}Assistant:{Colors.RESET}")
        await llm.chat(full_query)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="GodChat - AI-Powered Shell for God Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  godchat                           # Start REPL mode
  godchat "create 10 users"         # One-shot query
  godchat -f config.yaml "explain"  # Query with file context
  cat users.csv | godchat "analyze" # Pipe mode
  godchat --model gpt-4 "hello"     # Use specific model
"""
    )
    
    parser.add_argument("query", nargs="?", help="Query for CMD mode")
    parser.add_argument("-f", "--file", action="append", help="Input file(s)")
    parser.add_argument("-m", "--model", help="Model to use (local, gpt-4, claude-3)")
    parser.add_argument("--local", action="store_true", help="Force local LLM")
    parser.add_argument("--serve", action="store_true", help="Start as API server")
    
    args = parser.parse_args()
    
    # Load config
    config = Config.load()
    
    if args.model:
        config.default_model = args.model
    if args.local:
        config.default_model = "local"
    
    # Run appropriate mode
    if args.serve:
        print(f"{Colors.INFO}Starting GodChat server...{Colors.RESET}")
        # TODO: Implement server mode
        print(f"{Colors.ERROR}Server mode not yet implemented{Colors.RESET}")
    elif args.query or not sys.stdin.isatty():
        # CMD mode
        asyncio.run(cmd_mode(args.query or "", config, args.file))
    else:
        # REPL mode
        repl = GodChatREPL(config)
        asyncio.run(repl.run())


if __name__ == "__main__":
    main()
