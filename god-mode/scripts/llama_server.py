#!/usr/bin/env python3
"""
Llama Server Launcher for God Mode

Manages the llama.cpp server for local LLM inference.
Supports Windows (llama-server.exe) and Linux (llama-server).

Features:
- Auto-detect CPU capabilities and select optimal backend
- Download and manage GGUF models
- Start/stop/status server management
- Configuration via YAML or environment

Usage:
    python llama_server.py start           # Start server with defaults
    python llama_server.py start --model phi-3-mini  # Use specific model
    python llama_server.py stop            # Stop server
    python llama_server.py status          # Check server status
    python llama_server.py download <model>  # Download a model
"""

import os
import sys
import json
import subprocess
import platform
import signal
import time
import argparse
import urllib.request
import shutil
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ServerConfig:
    """Llama server configuration"""
    # Server settings
    host: str = "127.0.0.1"
    port: int = 8080
    threads: int = 4
    ctx_size: int = 4096
    batch_size: int = 512
    
    # Model settings
    model_path: str = ""
    model_name: str = "default"
    
    # Paths
    models_dir: str = str(Path.home() / ".godmode" / "models")
    bin_dir: str = str(Path.home() / ".godmode" / "bin")
    pid_file: str = str(Path.home() / ".godmode" / "llama.pid")
    log_file: str = str(Path.home() / ".godmode" / "llama.log")
    
    # CPU backend selection
    cpu_backend: str = "auto"  # auto, sse42, sandybridge, haswell, alderlake, skylakex, icelake
    
    @classmethod
    def load(cls) -> "ServerConfig":
        """Load config from file and environment"""
        config = cls()
        
        # Create directories
        Path(config.models_dir).mkdir(parents=True, exist_ok=True)
        Path(config.bin_dir).mkdir(parents=True, exist_ok=True)
        
        # Load from config file
        config_file = Path.home() / ".godmode" / "llama_config.json"
        if config_file.exists():
            with open(config_file) as f:
                data = json.load(f)
                for key, value in data.items():
                    if hasattr(config, key):
                        setattr(config, key, value)
        
        # Override from environment
        if os.environ.get("LLAMA_HOST"):
            config.host = os.environ["LLAMA_HOST"]
        if os.environ.get("LLAMA_PORT"):
            config.port = int(os.environ["LLAMA_PORT"])
        if os.environ.get("LLAMA_MODEL"):
            config.model_path = os.environ["LLAMA_MODEL"]
        
        return config
    
    def save(self):
        """Save config to file"""
        config_file = Path.home() / ".godmode" / "llama_config.json"
        with open(config_file, 'w') as f:
            json.dump(self.__dict__, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

MODELS = {
    # Small models (< 4GB)
    "phi-3-mini": {
        "url": "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf",
        "size": "2.2GB",
        "description": "Microsoft Phi-3 Mini - Fast and capable",
        "recommended_ctx": 4096
    },
    "qwen2.5-1.5b": {
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size": "1.1GB",
        "description": "Qwen 2.5 1.5B - Very fast, good for simple tasks",
        "recommended_ctx": 4096
    },
    "gemma-2b": {
        "url": "https://huggingface.co/google/gemma-2b-it-GGUF/resolve/main/gemma-2b-it-q4_k_m.gguf",
        "size": "1.5GB",
        "description": "Google Gemma 2B - Compact and efficient",
        "recommended_ctx": 2048
    },
    
    # Medium models (4-8GB)
    "llama-3.2-3b": {
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size": "2.0GB",
        "description": "Meta Llama 3.2 3B - Great balance of speed and quality",
        "recommended_ctx": 8192
    },
    "mistral-7b": {
        "url": "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
        "size": "4.4GB",
        "description": "Mistral 7B - Excellent general purpose model",
        "recommended_ctx": 8192
    },
    "qwen2.5-7b": {
        "url": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf",
        "size": "4.7GB",
        "description": "Qwen 2.5 7B - Strong coding and reasoning",
        "recommended_ctx": 8192
    },
    
    # Large models (> 8GB)
    "llama-3.1-8b": {
        "url": "https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "size": "4.9GB",
        "description": "Meta Llama 3.1 8B - High quality, versatile",
        "recommended_ctx": 8192
    },
    "deepseek-coder-6.7b": {
        "url": "https://huggingface.co/TheBloke/deepseek-coder-6.7B-instruct-GGUF/resolve/main/deepseek-coder-6.7b-instruct.Q4_K_M.gguf",
        "size": "4.1GB",
        "description": "DeepSeek Coder 6.7B - Excellent for code",
        "recommended_ctx": 4096
    }
}


# ═══════════════════════════════════════════════════════════════════════════════
# CPU DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_cpu_features() -> Dict[str, bool]:
    """Detect CPU features for optimal backend selection"""
    features = {
        "sse42": False,
        "avx": False,
        "avx2": False,
        "avx512": False,
        "avx512_vnni": False
    }
    
    system = platform.system()
    
    if system == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                cpuinfo = f.read().lower()
                features["sse42"] = "sse4_2" in cpuinfo
                features["avx"] = " avx " in cpuinfo or "avx " in cpuinfo
                features["avx2"] = "avx2" in cpuinfo
                features["avx512"] = "avx512" in cpuinfo
                features["avx512_vnni"] = "avx512_vnni" in cpuinfo
        except:
            pass
    
    elif system == "Windows":
        try:
            # Use wmic on Windows
            result = subprocess.run(
                ["wmic", "cpu", "get", "caption"],
                capture_output=True, text=True
            )
            # Basic detection based on CPU name
            cpu_name = result.stdout.lower()
            if "intel" in cpu_name:
                # Assume modern Intel has at least AVX2
                features["sse42"] = True
                features["avx"] = True
                features["avx2"] = True
                if any(x in cpu_name for x in ["12th", "13th", "14th", "alder", "raptor"]):
                    features["avx512"] = False  # Hybrid cores
                elif any(x in cpu_name for x in ["10th", "11th", "ice", "tiger"]):
                    features["avx512"] = True
                    features["avx512_vnni"] = True
            elif "amd" in cpu_name:
                features["sse42"] = True
                features["avx"] = True
                features["avx2"] = True
        except:
            pass
    
    return features


def select_backend(config: ServerConfig) -> str:
    """Select the optimal CPU backend based on features"""
    if config.cpu_backend != "auto":
        return config.cpu_backend
    
    features = detect_cpu_features()
    
    # Select best available backend
    if features["avx512_vnni"]:
        return "icelake"
    elif features["avx512"]:
        return "skylakex"
    elif features["avx2"]:
        return "haswell"
    elif features["avx"]:
        return "sandybridge"
    elif features["sse42"]:
        return "sse42"
    else:
        return "x64"


# ═══════════════════════════════════════════════════════════════════════════════
# SERVER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

class LlamaServer:
    """Manages the llama.cpp server process"""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
    
    def get_server_path(self) -> Path:
        """Get path to llama-server executable"""
        system = platform.system()
        
        if system == "Windows":
            exe_name = "llama-server.exe"
        else:
            exe_name = "llama-server"
        
        # Check in bin directory
        bin_path = Path(self.config.bin_dir) / exe_name
        if bin_path.exists():
            return bin_path
        
        # Check in current directory
        local_path = Path(exe_name)
        if local_path.exists():
            return local_path
        
        # Check in PATH
        which_result = shutil.which(exe_name)
        if which_result:
            return Path(which_result)
        
        return bin_path  # Return expected path even if not found
    
    def get_backend_dll(self) -> Optional[Path]:
        """Get path to CPU backend DLL (Windows only)"""
        if platform.system() != "Windows":
            return None
        
        backend = select_backend(self.config)
        dll_name = f"ggml-cpu-{backend}.dll"
        
        dll_path = Path(self.config.bin_dir) / dll_name
        if dll_path.exists():
            return dll_path
        
        return None
    
    def is_running(self) -> bool:
        """Check if server is running"""
        pid_file = Path(self.config.pid_file)
        if not pid_file.exists():
            return False
        
        try:
            pid = int(pid_file.read_text().strip())
            # Check if process exists
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True
                )
                return str(pid) in result.stdout
            else:
                os.kill(pid, 0)
                return True
        except (ValueError, OSError, ProcessLookupError):
            return False
    
    def get_pid(self) -> Optional[int]:
        """Get server PID if running"""
        pid_file = Path(self.config.pid_file)
        if pid_file.exists():
            try:
                return int(pid_file.read_text().strip())
            except ValueError:
                return None
        return None
    
    def start(self, model_path: Optional[str] = None) -> bool:
        """Start the llama server"""
        if self.is_running():
            print("Server is already running")
            return True
        
        server_path = self.get_server_path()
        if not server_path.exists():
            print(f"Error: llama-server not found at {server_path}")
            print("Please install llama.cpp or copy binaries to ~/.godmode/bin/")
            return False
        
        # Determine model path
        if model_path:
            model = Path(model_path)
        elif self.config.model_path:
            model = Path(self.config.model_path)
        else:
            # Look for any .gguf file in models directory
            models_dir = Path(self.config.models_dir)
            gguf_files = list(models_dir.glob("*.gguf"))
            if gguf_files:
                model = gguf_files[0]
            else:
                print("Error: No model found. Download one with: llama_server.py download <model>")
                print("\nAvailable models:")
                for name, info in MODELS.items():
                    print(f"  {name:20} {info['size']:>8}  {info['description']}")
                return False
        
        if not model.exists():
            print(f"Error: Model not found at {model}")
            return False
        
        # Build command
        cmd = [
            str(server_path),
            "-m", str(model),
            "--host", self.config.host,
            "--port", str(self.config.port),
            "-t", str(self.config.threads),
            "-c", str(self.config.ctx_size),
            "-b", str(self.config.batch_size),
        ]
        
        # Set environment for CPU backend (Windows)
        env = os.environ.copy()
        backend_dll = self.get_backend_dll()
        if backend_dll:
            env["GGML_CPU_BACKEND"] = str(backend_dll)
        
        # Start server
        print(f"Starting llama server...")
        print(f"  Model: {model.name}")
        print(f"  Endpoint: http://{self.config.host}:{self.config.port}")
        print(f"  CPU Backend: {select_backend(self.config)}")
        
        log_file = open(self.config.log_file, 'w')
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True
            )
            
            # Save PID
            Path(self.config.pid_file).write_text(str(self.process.pid))
            
            # Wait for server to start
            print("Waiting for server to start...")
            for i in range(30):
                time.sleep(1)
                if self._check_health():
                    print(f"\n✓ Server started successfully (PID: {self.process.pid})")
                    return True
                print(".", end="", flush=True)
            
            print("\n✗ Server failed to start. Check log:", self.config.log_file)
            return False
            
        except Exception as e:
            print(f"Error starting server: {e}")
            return False
    
    def stop(self) -> bool:
        """Stop the llama server"""
        pid = self.get_pid()
        if not pid:
            print("Server is not running")
            return True
        
        try:
            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            
            # Remove PID file
            Path(self.config.pid_file).unlink(missing_ok=True)
            print(f"✓ Server stopped (PID: {pid})")
            return True
            
        except Exception as e:
            print(f"Error stopping server: {e}")
            return False
    
    def status(self) -> Dict:
        """Get server status"""
        running = self.is_running()
        pid = self.get_pid()
        
        status = {
            "running": running,
            "pid": pid,
            "endpoint": f"http://{self.config.host}:{self.config.port}",
            "model": self.config.model_path or "default",
            "cpu_backend": select_backend(self.config)
        }
        
        if running:
            health = self._check_health()
            status["healthy"] = health
        
        return status
    
    def _check_health(self) -> bool:
        """Check if server is healthy"""
        try:
            url = f"http://{self.config.host}:{self.config.port}/health"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as response:
                return response.status == 200
        except:
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def download_model(model_name: str, config: ServerConfig) -> bool:
    """Download a model from the registry"""
    if model_name not in MODELS:
        print(f"Error: Unknown model '{model_name}'")
        print("\nAvailable models:")
        for name, info in MODELS.items():
            print(f"  {name:20} {info['size']:>8}  {info['description']}")
        return False
    
    model_info = MODELS[model_name]
    url = model_info["url"]
    filename = url.split("/")[-1]
    dest_path = Path(config.models_dir) / filename
    
    if dest_path.exists():
        print(f"Model already exists: {dest_path}")
        return True
    
    print(f"Downloading {model_name} ({model_info['size']})...")
    print(f"  From: {url}")
    print(f"  To: {dest_path}")
    
    try:
        # Download with progress
        def progress_hook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(100, downloaded * 100 / total_size)
                mb_downloaded = downloaded / (1024 * 1024)
                mb_total = total_size / (1024 * 1024)
                print(f"\r  Progress: {percent:.1f}% ({mb_downloaded:.1f}/{mb_total:.1f} MB)", end="", flush=True)
        
        urllib.request.urlretrieve(url, dest_path, progress_hook)
        print(f"\n✓ Downloaded: {dest_path}")
        
        # Update config with new model
        config.model_path = str(dest_path)
        config.save()
        
        return True
        
    except Exception as e:
        print(f"\nError downloading model: {e}")
        if dest_path.exists():
            dest_path.unlink()
        return False


def list_models(config: ServerConfig):
    """List available and downloaded models"""
    print("\n=== Available Models ===")
    for name, info in MODELS.items():
        print(f"  {name:20} {info['size']:>8}  {info['description']}")
    
    print("\n=== Downloaded Models ===")
    models_dir = Path(config.models_dir)
    gguf_files = list(models_dir.glob("*.gguf"))
    if gguf_files:
        for f in gguf_files:
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  {f.name:40} {size_mb:.1f} MB")
    else:
        print("  No models downloaded yet")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Llama Server Launcher for God Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  start              Start the llama server
  stop               Stop the llama server
  restart            Restart the llama server
  status             Show server status
  download <model>   Download a model
  list               List available models

Examples:
  python llama_server.py start
  python llama_server.py start --model ~/.godmode/models/phi-3-mini.gguf
  python llama_server.py download mistral-7b
  python llama_server.py status
"""
    )
    
    parser.add_argument("command", choices=["start", "stop", "restart", "status", "download", "list"])
    parser.add_argument("model", nargs="?", help="Model name for download command")
    parser.add_argument("--model", "-m", dest="model_path", help="Path to model file")
    parser.add_argument("--port", "-p", type=int, help="Server port")
    parser.add_argument("--host", "-H", help="Server host")
    parser.add_argument("--threads", "-t", type=int, help="Number of threads")
    parser.add_argument("--ctx-size", "-c", type=int, help="Context size")
    parser.add_argument("--backend", "-b", choices=["auto", "sse42", "sandybridge", "haswell", "alderlake", "skylakex", "icelake"],
                       help="CPU backend")
    
    args = parser.parse_args()
    
    # Load config
    config = ServerConfig.load()
    
    # Apply command line overrides
    if args.port:
        config.port = args.port
    if args.host:
        config.host = args.host
    if args.threads:
        config.threads = args.threads
    if args.ctx_size:
        config.ctx_size = args.ctx_size
    if args.backend:
        config.cpu_backend = args.backend
    
    # Create server instance
    server = LlamaServer(config)
    
    # Execute command
    if args.command == "start":
        server.start(args.model_path)
    
    elif args.command == "stop":
        server.stop()
    
    elif args.command == "restart":
        server.stop()
        time.sleep(2)
        server.start(args.model_path)
    
    elif args.command == "status":
        status = server.status()
        print("\n=== Llama Server Status ===")
        print(f"  Running: {'✓ Yes' if status['running'] else '✗ No'}")
        if status['running']:
            print(f"  PID: {status['pid']}")
            print(f"  Healthy: {'✓ Yes' if status.get('healthy') else '✗ No'}")
        print(f"  Endpoint: {status['endpoint']}")
        print(f"  CPU Backend: {status['cpu_backend']}")
        print(f"  Model: {status['model']}")
    
    elif args.command == "download":
        if not args.model:
            print("Error: Please specify a model name")
            list_models(config)
        else:
            download_model(args.model, config)
    
    elif args.command == "list":
        list_models(config)


if __name__ == "__main__":
    main()
