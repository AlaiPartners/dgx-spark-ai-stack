#!/usr/bin/env python3
"""
Interactive CLI to add new models to the docker-compose setup.
Downloads from HuggingFace and adds service configuration.
"""

import argparse
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, List

try:
    from huggingface_hub import hf_hub_download, list_repo_files
    import ruamel.yaml
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn
    from rich.text import Text
    from rich.live import Live
    from rich import box
    try:
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.keys import Keys
        from prompt_toolkit.layout import Layout, HSplit, VSplit
        from prompt_toolkit.widgets import TextArea
        from prompt_toolkit.shortcuts import prompt as pt_prompt
        PROMPT_TOOLKIT_AVAILABLE = True
    except ImportError:
        PROMPT_TOOLKIT_AVAILABLE = False
except ImportError as e:
    if 'rich' in str(e) or 'huggingface_hub' in str(e) or 'ruamel' in str(e):
        print("Error: Required packages not found.")
        print("Please set up the virtualenv first:")
        print("  ./setup_venv.sh")
        print("  source venv/bin/activate")
        print("  python add_model.py ...")
    else:
        print(f"Error: {e}")
    sys.exit(1)

console = Console()

# Global flags
_in_operation = False
_exit_requested = False


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully with confirmation."""
    global _in_operation
    
    if _in_operation:
        # If in the middle of an operation, just exit
        console.print("\n[yellow]Interrupted during operation. Exiting...[/yellow]")
        sys.exit(1)
    
    # Raise KeyboardInterrupt so safe_prompt can catch it
    raise KeyboardInterrupt


# Register signal handler
signal.signal(signal.SIGINT, signal_handler)


def check_exit_requested():
    """Check if exit was requested and handle confirmation."""
    global _exit_requested
    if _exit_requested:
        _exit_requested = False
        if Confirm.ask("[bold yellow]Really exit?[/bold yellow]", default=False):
            console.print("[yellow]Exiting...[/yellow]")
            sys.exit(0)
        else:
            console.print("[cyan]Continuing...[/cyan]")


def safe_prompt(prompt_func, *args, **kwargs):
    """Wrapper for prompts that handles Ctrl+C immediately."""
    try:
        return prompt_func(*args, **kwargs)
    except KeyboardInterrupt:
        console.print()
        if Confirm.ask("[bold yellow]Really exit?[/bold yellow]", default=False):
            console.print("[yellow]Exiting...[/yellow]")
            sys.exit(0)
        else:
            console.print("[cyan]Continuing...[/cyan]")
            # Retry the prompt
            return prompt_func(*args, **kwargs)


def interactive_confirm(prompt_text: str, default: bool = True) -> bool:
    """Simple yes/no prompt - just use Rich's built-in for now."""
    # For now, use simple Rich Confirm - it works well and is clean
    return safe_prompt(Confirm.ask, prompt_text, default=default)


def browse_for_file(start_dir: str, file_extension: str = '.gguf', description: str = "model file") -> Optional[str]:
    """Interactive file browser with arrow key navigation."""
    current_dir = Path(start_dir).expanduser().resolve()
    selected_idx = 0
    
    # Ensure starting directory exists
    if not current_dir.exists():
        console.print(f"[yellow]Warning:[/yellow] Starting directory does not exist: {start_dir}")
        console.print(f"[yellow]Creating:[/yellow] {current_dir}")
        current_dir.mkdir(parents=True, exist_ok=True)
    
    if not current_dir.is_dir():
        console.print(f"[bold red]Error:[/bold red] Not a directory: {start_dir}")
        return None
    
    def get_entries():
        """Get list of entries in current directory."""
        entries = []
        # Add parent directory option
        if current_dir.parent != current_dir:
            entries.append(('..', current_dir.parent, True))
        
        # List files and directories
        try:
            for item in sorted(current_dir.iterdir()):
                if item.is_dir():
                    entries.append((item.name, item, True))
                elif item.is_file() and (file_extension is None or item.suffix.lower() == file_extension.lower()):
                    entries.append((item.name, item, False))
        except PermissionError:
            pass
        
        return entries
    
    def render_table(entries, selected):
        """Render the file browser table with selection highlight."""
        file_table = Table(
            title=f"[cyan]Contents of {current_dir.name}[/cyan]",
            box=box.ROUNDED,
            show_header=True
        )
        file_table.add_column("", style="cyan", width=3, justify="center")
        file_table.add_column("Name", style="white")
        file_table.add_column("Type", style="dim")
        file_table.add_column("Size", style="dim", justify="right")
        
        for idx, (name, path, is_dir) in enumerate(entries):
            marker = "▶" if idx == selected else " "
            if is_dir:
                name_style = f"[bold cyan]{name}/[/bold cyan]"
            else:
                name_style = name
            
            if idx == selected:
                name_style = f"[reverse]{name_style}[/reverse]"
            
            if is_dir:
                file_table.add_row(marker, name_style, "Directory", "-")
            else:
                try:
                    size = path.stat().st_size
                    size_str = f"{size / (1024**3):.2f} GB" if size > 1024**3 else \
                              f"{size / (1024**2):.2f} MB" if size > 1024**2 else \
                              f"{size / 1024:.2f} KB"
                except:
                    size_str = "?"
                file_table.add_row(marker, name_style, "File", size_str)
        
        return file_table
    
    while True:
        entries = get_entries()
        
        if not entries:
            console.print(f"[yellow]No {description}s found in this directory[/yellow]")
            if current_dir.parent != current_dir:
                current_dir = current_dir.parent
                selected_idx = 0
                continue
            else:
                return None
        
        # Ensure selected_idx is valid
        if selected_idx >= len(entries):
            selected_idx = 0
        if selected_idx < 0:
            selected_idx = len(entries) - 1
        
        # Render the interface
        console.clear()
        console.print()
        console.print(Panel(
            f"[bold]Browse for {description}[/bold]\n\n"
            f"Current directory: [cyan]{current_dir}[/cyan]\n\n"
            "[dim]Use arrow keys to navigate, Enter to select, 'q' to quit[/dim]",
            title="[cyan]File Browser[/cyan]",
            border_style="cyan"
        ))
        console.print()
        
        file_table = render_table(entries, selected_idx)
        console.print(file_table)
        console.print()
        console.print("[dim]↑↓: Navigate  Enter: Select  q: Quit[/dim]")
        
        # Get user input with arrow key support
        try:
            if PROMPT_TOOLKIT_AVAILABLE:
                # Use prompt_toolkit for interactive navigation
                from prompt_toolkit.shortcuts import prompt
                from prompt_toolkit.key_binding import KeyBindings
                from prompt_toolkit import print_formatted_text as pt_print
                
                kb = KeyBindings()
                nav_state = {'idx': selected_idx, 'action': None}
                
                @kb.add('up')
                def go_up(event):
                    nav_state['idx'] = max(0, nav_state['idx'] - 1)
                    # Re-render
                    console.clear()
                    console.print()
                    console.print(Panel(
                        f"[bold]Browse for {description}[/bold]\n\n"
                        f"Current directory: [cyan]{current_dir}[/cyan]\n\n"
                        "[dim]Use arrow keys to navigate, Enter to select, 'q' to quit[/dim]",
                        title="[cyan]File Browser[/cyan]",
                        border_style="cyan"
                    ))
                    console.print()
                    file_table = render_table(entries, nav_state['idx'])
                    console.print(file_table)
                    console.print()
                    console.print("[dim]↑↓: Navigate  Enter: Select  q: Quit[/dim]")
                
                @kb.add('down')
                def go_down(event):
                    nav_state['idx'] = min(len(entries) - 1, nav_state['idx'] + 1)
                    # Re-render
                    console.clear()
                    console.print()
                    console.print(Panel(
                        f"[bold]Browse for {description}[/bold]\n\n"
                        f"Current directory: [cyan]{current_dir}[/cyan]\n\n"
                        "[dim]Use arrow keys to navigate, Enter to select, 'q' to quit[/dim]",
                        title="[cyan]File Browser[/cyan]",
                        border_style="cyan"
                    ))
                    console.print()
                    file_table = render_table(entries, nav_state['idx'])
                    console.print(file_table)
                    console.print()
                    console.print("[dim]↑↓: Navigate  Enter: Select  q: Quit[/dim]")
                
                @kb.add('enter')
                def select(event):
                    nav_state['action'] = 'select'
                    event.app.exit()
                
                @kb.add('q')
                def quit(event):
                    nav_state['action'] = 'quit'
                    event.app.exit()
                
                @kb.add('c-c')
                def interrupt(event):
                    nav_state['action'] = 'quit'
                    event.app.exit()
                
                # Create prompt that captures keys
                try:
                    prompt('', key_bindings=kb, default='')
                except EOFError:
                    return None
                
                selected_idx = nav_state['idx']
                
                if nav_state['action'] == 'quit':
                    return None
                elif nav_state['action'] == 'select':
                    selected_name, selected_path, is_dir = entries[selected_idx]
                    if is_dir:
                        current_dir = selected_path
                        selected_idx = 0
                        continue
                    else:
                        return str(selected_path)
                else:
                    # Just navigation, continue loop
                    continue
            else:
                # Fallback to text input
                choice = safe_prompt(Prompt.ask, "[bold cyan]Select (↑↓/number/path/../q)[/bold cyan]")
                choice = choice.strip()
                
                if choice.lower() == 'q':
                    return None
                
                if choice == '..':
                    if current_dir.parent != current_dir:
                        current_dir = current_dir.parent
                        selected_idx = 0
                    continue
                
                # Try to parse as number
                try:
                    idx = int(choice)
                    if 1 <= idx <= len(entries):
                        selected_name, selected_path, is_dir = entries[idx - 1]
                        if is_dir:
                            current_dir = selected_path
                            selected_idx = 0
                            continue
                        else:
                            return str(selected_path)
                    else:
                        console.print(f"[bold red]Error:[/bold red] Invalid number. Choose 1-{len(entries)}")
                        continue
                except ValueError:
                    # Not a number, treat as path
                    path_input = Path(choice).expanduser()
                    if path_input.is_absolute():
                        target_path = path_input
                    else:
                        target_path = current_dir / path_input
                    
                    target_path = target_path.resolve()
                    
                    if target_path.exists() and target_path.is_dir():
                        current_dir = target_path
                        selected_idx = 0
                        continue
                    elif target_path.exists() and target_path.is_file():
                        if file_extension is None or target_path.suffix.lower() == file_extension.lower():
                            return str(target_path)
                        else:
                            console.print(f"[bold red]Error:[/bold red] File must have {file_extension} extension")
                            continue
                    else:
                        console.print(f"[bold red]Error:[/bold red] Path not found: {choice}")
                        continue
        except KeyboardInterrupt:
            return None

def load_models_dir_from_env() -> str:
    """Load MODELS_DIR from .env file, expanding $HOME, defaulting to ./models."""
    env_file = Path(".env")
    if env_file.exists():
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    # Parse KEY=VALUE format
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key == 'MODELS_DIR':
                            # Expand $HOME and other environment variables
                            value = os.path.expandvars(value)
                            return value
        except Exception:
            pass
    # Default fallback - also expand vars from environment
    models_dir = os.getenv('MODELS_DIR', './models')
    return os.path.expandvars(models_dir)


yaml = ruamel.yaml.YAML()
yaml.preserve_quotes = True
yaml.width = 4096


def sanitize_name(name: str) -> str:
    """Convert model name to valid service/container name."""
    # Replace invalid chars with hyphens, lowercase
    name = re.sub(r'[^a-z0-9-]', '-', name.lower())
    # Remove multiple hyphens
    name = re.sub(r'-+', '-', name)
    # Remove leading/trailing hyphens
    return name.strip('-')


def find_model_file(repo_id: str, quant: str) -> Optional[str]:
    """Find the model file in the repo matching quantization."""
    try:
        files = list_repo_files(repo_id, repo_type="model")
        # Look for .gguf files with quantization in name
        pattern = re.compile(rf'.*{re.escape(quant)}.*\.gguf$', re.IGNORECASE)
        for f in files:
            if pattern.search(f):
                return f
        # Fallback: look for any .gguf file
        for f in files:
            if f.endswith('.gguf') and 'model' in f.lower():
                return f
    except Exception as e:
        print(f"Warning: Could not list repo files: {e}")
    return None


def find_mmproj_file(repo_id: str) -> Optional[str]:
    """Find the mmproj file for vision models."""
    try:
        files = list_repo_files(repo_id, repo_type="model")
        for f in files:
            if 'mmproj' in f.lower() and f.endswith('.gguf'):
                return f
    except Exception:
        pass
    return None


def prompt_download_directory(models_dir: str, default_name: str) -> str:
    """Prompt user to select or enter a directory name within models_dir."""
    models_dir_path = Path(models_dir).expanduser().resolve()
    
    # List existing directories
    existing_dirs = []
    if models_dir_path.exists() and models_dir_path.is_dir():
        try:
            for item in models_dir_path.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    existing_dirs.append(item.name)
        except PermissionError:
            pass
    
    existing_dirs = sorted(existing_dirs)
    
    console.print()
    console.print(Panel(
        "[bold]Download Directory[/bold]\n\n"
        "Choose where to download the model within the models directory.",
        title="[cyan]Directory Selection[/cyan]",
        border_style="cyan"
    ))
    console.print()
    
    if existing_dirs:
        console.print("[bold]Existing directories:[/bold]")
        dir_table = Table(box=box.SIMPLE, show_header=False)
        dir_table.add_column("#", style="cyan", width=4, justify="right")
        dir_table.add_column("Directory", style="white")
        
        for idx, dir_name in enumerate(existing_dirs, 1):
            dir_table.add_row(str(idx), dir_name)
        
        console.print(dir_table)
        console.print()
        
        use_existing = interactive_confirm(
            "[bold cyan]Use an existing directory?[/bold cyan]",
            default=False
        )
        
        if use_existing:
            while True:
                try:
                    choice = safe_prompt(Prompt.ask, "[bold cyan]Select directory number[/bold cyan]")
                    idx = int(choice)
                    if 1 <= idx <= len(existing_dirs):
                        selected_dir = existing_dirs[idx - 1]
                        console.print(f"[green]Selected:[/green] [cyan]{selected_dir}[/cyan]")
                        return selected_dir
                    else:
                        console.print(f"[bold red]Error:[/bold red] Invalid number. Choose 1-{len(existing_dirs)}")
                except ValueError:
                    console.print(f"[bold red]Error:[/bold red] Please enter a number")
                except KeyboardInterrupt:
                    return default_name
    
    # Enter new directory name
    console.print()
    dir_name = safe_prompt(
        Prompt.ask,
        "[bold cyan]Enter directory name[/bold cyan]",
        default=default_name
    )
    
    return dir_name


def download_model(repo_id: str, model_file: str, mmproj_file: Optional[str], 
                   models_dir: str, model_dir_name: str) -> Tuple[str, Optional[str]]:
    """Download model and mmproj files with progress bar."""
    global _in_operation
    model_dir = Path(models_dir).expanduser().resolve() / model_dir_name
    model_dir.mkdir(parents=True, exist_ok=True)
    
    _in_operation = True
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console
        ) as progress:
            task1 = progress.add_task(f"[cyan]Downloading model: {model_file}", total=None)
            model_path = hf_hub_download(
                repo_id=repo_id,
                filename=model_file,
                local_dir=str(model_dir),
                local_dir_use_symlinks=False
            )
            progress.update(task1, completed=True)
            
            mmproj_path = None
            if mmproj_file:
                task2 = progress.add_task(f"[cyan]Downloading mmproj: {mmproj_file}", total=None)
                mmproj_path = hf_hub_download(
                    repo_id=repo_id,
                    filename=mmproj_file,
                    local_dir=str(model_dir),
                    local_dir_use_symlinks=False
                )
                progress.update(task2, completed=True)
    finally:
        _in_operation = False
    
    return model_path, mmproj_path


def get_next_port(compose_data: dict) -> int:
    """Find next available port starting from 8001."""
    used_ports = set()
    for service_name, service_config in compose_data.get('services', {}).items():
        if 'llamacpp' in service_name:
            used_ports.add(8001)
    
    port = 8001
    while port in used_ports:
        port += 1
    return port


def add_service_to_compose(compose_path: str, service_name: str, container_name: str,
                           model_path: str, mmproj_path: Optional[str], models_dir: str):
    """Add new service to docker-compose.yml."""
    with open(compose_path, 'r') as f:
        compose = yaml.load(f)
    
    # Expand tilde and resolve models_dir
    models_dir_expanded = Path(models_dir).expanduser().resolve()
    
    # Convert model path to relative path in container
    model_path_resolved = Path(model_path).resolve()
    model_rel = str(model_path_resolved.relative_to(models_dir_expanded))
    model_env = f"/models/{model_rel}"
    
    mmproj_env = None
    if mmproj_path:
        mmproj_path_resolved = Path(mmproj_path).resolve()
        mmproj_rel = str(mmproj_path_resolved.relative_to(models_dir_expanded))
        mmproj_env = f"/models/{mmproj_rel}"
    
    # Create service config using pre-built image
    service_config = {
        'image': 'cslev/llamacpp-cuda-arm64:latest',
        'container_name': container_name,
        'restart': 'unless-stopped',
        'volumes': [
            f"${{MODELS_DIR:-./models}}:/models:ro",
            './logs:/logs'
        ],
        'environment': [
            'CUDA_VISIBLE_DEVICES=0'
        ],
        'networks': ['spark-network'],
        'deploy': {
            'resources': {
                'reservations': {
                    'devices': [{
                        'driver': 'nvidia',
                        'device_ids': ['0'],
                        'capabilities': ['gpu']
                    }]
                }
            }
        }
    }
    
    # Build command as list (ruamel.yaml will format it as YAML multiline)
    ctx_size = '32768' if mmproj_env else '16384'
    command_parts = [
        '--host', '0.0.0.0',
        '--port', '8001',
        '--ctx-size', ctx_size,
        '--threads', '8',
        '--n-gpu-layers', '99',
        '--model', model_env,
        '--flash-attn', 'on'
    ]
    
    # Add mmproj for vision models
    if mmproj_env:
        command_parts.extend(['--mmproj', mmproj_env])
    
    service_config['command'] = command_parts
    
    compose['services'][service_name] = service_config
    
    with open(compose_path, 'w') as f:
        yaml.dump(compose, f)
    
    console.print(f"[green][OK][/green] Added service '[cyan]{service_name}[/cyan]' to docker-compose.yml")


def update_llama_swap(swap_config_path: str, model_id: str, service_name: str):
    """Add model to llama-swap config."""
    if not os.path.exists(swap_config_path):
        print(f"Warning: llama-swap config not found at {swap_config_path}")
        return
    
    with open(swap_config_path, 'r') as f:
        config = yaml.load(f)
    
    if 'models' not in config:
        config['models'] = {}
    
    # Use service name as proxy target
    config['models'][model_id] = {
        'proxy': f'http://{service_name}:8001',
        'checkEndpoint': '/health',
        'cmd': 'sleep infinity'
    }
    
    with open(swap_config_path, 'w') as f:
        yaml.dump(config, f)
    
    console.print(f"[green][OK][/green] Added '[cyan]{model_id}[/cyan]' to llama-swap config")


def find_available_quantizations(repo_id: str) -> List[str]:
    """Find available quantization files in the repo."""
    try:
        files = list_repo_files(repo_id, repo_type="model")
        quants = set()
        for f in files:
            if f.endswith('.gguf') and 'model' in f.lower():
                # Extract quantization from filename
                for q in ['Q2_K', 'Q3_K_S', 'Q3_K_M', 'Q3_K_L', 'Q4_K_S', 'Q4_K_M', 
                          'Q5_K_S', 'Q5_K_M', 'Q6_K', 'Q8_0', 'F16', 'F32']:
                    if q in f.upper():
                        quants.add(q)
        return sorted(list(quants), key=lambda x: ['Q2_K', 'Q3_K_S', 'Q3_K_M', 'Q3_K_L', 
                                                    'Q4_K_S', 'Q4_K_M', 'Q5_K_S', 'Q5_K_M', 
                                                    'Q6_K', 'Q8_0', 'F16', 'F32'].index(x) 
                     if x in ['Q2_K', 'Q3_K_S', 'Q3_K_M', 'Q3_K_L', 'Q4_K_S', 'Q4_K_M', 
                             'Q5_K_S', 'Q5_K_M', 'Q6_K', 'Q8_0', 'F16', 'F32'] else 999)
    except Exception:
        return []


def prompt_user() -> dict:
    """Interactive prompts to gather model information with rich formatting."""
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Add New Model to Docker Compose[/bold cyan]\n\n"
        "[dim]This wizard will help you add a new model to your deployment[/dim]",
        border_style="cyan"
    ))
    console.print()
    
    # Step 0: Choose source
    console.print(Panel(
        "[bold]Model Source[/bold]\n\n"
        "Choose where to get the model from:\n"
        "  • Download from HuggingFace\n"
        "  • Use a local model file",
        title="[cyan]Source[/cyan]",
        border_style="cyan"
    ))
    use_local = interactive_confirm("[bold cyan]Use local model file?[/bold cyan]", default=False)
    
    repo_id = None
    quant = None
    is_vision = False
    mmproj_file = None
    local_model_path = None
    local_mmproj_path = None
    
    if use_local:
        # Local model flow
        console.print()
        default_models_dir = load_models_dir_from_env()
        
        # Ask if user wants to browse or type path
        console.print()
        use_browser = interactive_confirm(
            "[bold cyan]Browse models directory to select file?[/bold cyan]", 
            default=True)
        
        if use_browser:
            console.print()
            local_model_path = browse_for_file(default_models_dir, '.gguf', "model file")
            if not local_model_path:
                console.print("[yellow]No file selected. Exiting...[/yellow]")
                sys.exit(0)
        else:
            console.print()
            console.print()
            console.print(Panel(
                "[bold]Local Model File[/bold]\n\n"
                "Enter the path to your local .gguf model file.\n"
                "[dim]Example: /path/to/model.gguf or ./models/my-model.gguf[/dim]",
                title="[cyan]Model Path[/cyan]",
                border_style="cyan"
            ))
            while True:
                local_model_path = safe_prompt(Prompt.ask, "[bold cyan]Model file path[/bold cyan]")
                model_path_obj = Path(local_model_path).expanduser().resolve()
                if not model_path_obj.exists():
                    console.print(f"[bold red]Error:[/bold red] File not found: {local_model_path}")
                    if not safe_prompt(Confirm.ask, "[yellow]Try again?[/yellow]", default=True):
                        sys.exit(1)
                    continue
                if not model_path_obj.is_file():
                    console.print(f"[bold red]Error:[/bold red] Not a file: {local_model_path}")
                    if not safe_prompt(Confirm.ask, "[yellow]Try again?[/yellow]", default=True):
                        sys.exit(1)
                    continue
                if not model_path_obj.suffix.lower() == '.gguf':
                    console.print(f"[yellow]Warning:[/yellow] File doesn't have .gguf extension")
                    if not safe_prompt(Confirm.ask, "[yellow]Continue anyway?[/yellow]", default=True):
                        continue
                break
        
        model_path_obj = Path(local_model_path).expanduser().resolve()
        
        # Check for vision model
        console.print()
        is_vision = interactive_confirm("[bold cyan]Is this a vision model?[/bold cyan]", default=False)
        if is_vision:
            # Look for mmproj in the same directory as the model
            model_dir = model_path_obj.parent
            mmproj_candidates = list(model_dir.glob("*mmproj*.gguf"))
            
            if mmproj_candidates:
                console.print()
                console.print(f"[green]Found {len(mmproj_candidates)} mmproj file(s) in the same directory[/green]")
                use_browser_mmproj = interactive_confirm(
                    "[bold cyan]Browse to select mmproj file?[/bold cyan]",
                    default=True)
                
                if use_browser_mmproj:
                    local_mmproj_path = browse_for_file(str(model_dir), '.gguf', "mmproj file")
                else:
                    console.print()
                    console.print(Panel(
                        "[bold]MMProj File[/bold]\n\n"
                        "Enter the path to the mmproj file for this vision model.\n"
                        "[dim]Example: /path/to/mmproj.gguf[/dim]",
                        title="[cyan]MMProj Path[/cyan]",
                        border_style="cyan"
                    ))
                    while True:
                        local_mmproj_path = safe_prompt(Prompt.ask, "[bold cyan]MMProj file path[/bold cyan]")
                        if not local_mmproj_path:
                            local_mmproj_path = None
                            break
                        mmproj_path_obj = Path(local_mmproj_path).expanduser().resolve()
                        if not mmproj_path_obj.exists():
                            console.print(f"[bold red]Error:[/bold red] File not found: {local_mmproj_path}")
                            if not safe_prompt(Confirm.ask, "[yellow]Try again?[/yellow]", default=True):
                                local_mmproj_path = None
                                break
                            continue
                        if not mmproj_path_obj.is_file():
                            console.print(f"[bold red]Error:[/bold red] Not a file: {local_mmproj_path}")
                            if not safe_prompt(Confirm.ask, "[yellow]Try again?[/yellow]", default=True):
                                local_mmproj_path = None
                                break
                            continue
                        break
            else:
                console.print()
                console.print(Panel(
                    "[bold]MMProj File[/bold]\n\n"
                    "Enter the path to the mmproj file for this vision model.\n"
                    "[dim]Example: /path/to/mmproj.gguf[/dim]",
                    title="[cyan]MMProj Path[/cyan]",
                    border_style="cyan"
                ))
                use_browser_mmproj = interactive_confirm(
                    "[bold cyan]Browse to select mmproj file?[/bold cyan]",
                    default=True)
                
                if use_browser_mmproj:
                    local_mmproj_path = browse_for_file(str(model_dir), '.gguf', "mmproj file")
                else:
                    while True:
                        local_mmproj_path = safe_prompt(Prompt.ask, "[bold cyan]MMProj file path[/bold cyan]")
                        if not local_mmproj_path:
                            local_mmproj_path = None
                            break
                        mmproj_path_obj = Path(local_mmproj_path).expanduser().resolve()
                        if not mmproj_path_obj.exists():
                            console.print(f"[bold red]Error:[/bold red] File not found: {local_mmproj_path}")
                            if not safe_prompt(Confirm.ask, "[yellow]Try again?[/yellow]", default=True):
                                local_mmproj_path = None
                                break
                            continue
                        if not mmproj_path_obj.is_file():
                            console.print(f"[bold red]Error:[/bold red] Not a file: {local_mmproj_path}")
                            if not safe_prompt(Confirm.ask, "[yellow]Try again?[/yellow]", default=True):
                                local_mmproj_path = None
                                break
                            continue
                        break
        
        # Extract model name from path for default service name
        model_name = model_path_obj.stem.replace('.gguf', '').replace('_GGUF', '').replace('-GGUF', '')
    else:
        # HuggingFace flow
        console.print()
        console.print(Panel(
            "[bold]Step 1: HuggingFace Repository[/bold]\n\n"
            "Enter the HuggingFace repository ID for the model.\n"
            "[dim]Example: meta-llama/Meta-Llama-3.1-8B-Instruct-GGUF[/dim]",
            title="[cyan]Repository[/cyan]",
            border_style="cyan"
        ))
        repo_id = safe_prompt(Prompt.ask, "[bold cyan]Repository ID[/bold cyan]")
        if not repo_id:
            console.print("[bold red]Error:[/bold red] Repo ID is required")
            sys.exit(1)
        
        global _in_operation
        _in_operation = True
        try:
            with console.status("[bold cyan]Checking repository...[/bold cyan]", spinner="dots"):
                # Find available quantizations
                quants = find_available_quantizations(repo_id)
                mmproj_file = find_mmproj_file(repo_id)
                is_vision = mmproj_file is not None
        finally:
            _in_operation = False
    
    # Step 2: Quantization (only for HuggingFace)
    if not use_local:
        console.print()
        quant_table = Table(title="[cyan]Step 2: Quantization Level[/cyan]", box=box.ROUNDED, show_header=True)
        quant_table.add_column("Option", style="cyan", no_wrap=True)
        quant_table.add_column("Description", style="white")
        
        if quants:
            quant_table.add_row("Available", ", ".join(quants))
            quant_table.add_row("Q4_K_M", "Balanced (recommended)")
            quant_table.add_row("Q5_K_M", "Better quality, larger size")
            quant_table.add_row("Q8_0", "Best quality, largest size")
            console.print(quant_table)
            default_quant = quants[0] if quants else 'Q4_K_M'
            quant = safe_prompt(Prompt.ask, f"[bold cyan]Choose quantization[/bold cyan]", default=default_quant).upper()
            if quant not in quants:
                console.print(f"[yellow]Warning:[/yellow] {quant} not found in available files, but will try anyway...")
        else:
            console.print("[yellow]Could not detect available quantizations automatically.[/yellow]")
            quant = safe_prompt(Prompt.ask, "[bold cyan]Enter quantization level[/bold cyan]", default="Q4_K_M").upper()
    
    # Model type info
    console.print()
    model_type_text = Text()
    if is_vision:
        model_type_text.append("Vision Model", style="bold green")
        model_type_text.append(f" (MMProj: {mmproj_file})", style="dim")
    else:
        model_type_text.append("Text Model", style="bold blue")
    
    console.print(Panel(
        model_type_text,
        title="[cyan]Model Type Detected[/cyan]",
        border_style="green" if is_vision else "blue"
    ))
    
    # Step 3: Service Configuration
    console.print()
    if use_local:
        # Use model name from path
        default_service = f"llamacpp-{sanitize_name(model_name)}"
    else:
        model_name = repo_id.split('/')[-1].replace('-GGUF', '').replace('_GGUF', '')
        default_service = f"llamacpp-{sanitize_name(model_name)}"
    
    console.print(Panel(
        "[bold]Service Configuration[/bold]\n\n"
        "The service name will be used for:\n"
        "  • Docker container name\n"
        "  • Service name in docker-compose.yml\n"
        "  • Network hostname",
        title="[cyan]Service Name[/cyan]",
        border_style="cyan"
    ))
    service_name = safe_prompt(Prompt.ask, "[bold cyan]Service name[/bold cyan]", default=default_service)
    service_name = sanitize_name(service_name) if service_name != default_service else default_service
    container_name = service_name.replace('_', '-')
    model_id = service_name.replace('llamacpp-', '')
    
    # Step 4: Storage
    console.print()
    default_models_dir = load_models_dir_from_env()
    models_dir = safe_prompt(Prompt.ask, "[bold cyan]Models directory[/bold cyan]", default=default_models_dir)
    
    # Step 5: Configuration options
    console.print()
    console.print(Panel(
        "[bold]Configuration Options[/bold]",
        title="[cyan]Options[/cyan]",
        border_style="cyan"
    ))
    use_swap = interactive_confirm("[bold cyan]Add to llama-swap config?[/bold cyan]", default=True)
    console.print()
    auto_start = interactive_confirm("[bold cyan]Start service after adding?[/bold cyan]", default=True)
    
    # Summary
    console.print()
    summary_table = Table(title="[bold green]Summary[/bold green]", box=box.ROUNDED, show_header=False)
    summary_table.add_column("Setting", style="cyan", width=20)
    summary_table.add_column("Value", style="white")
    
    if use_local:
        summary_table.add_row("Source", "[cyan]Local File[/cyan]")
        summary_table.add_row("Model Path", str(local_model_path))
        if local_mmproj_path:
            summary_table.add_row("MMProj Path", str(local_mmproj_path))
    else:
        summary_table.add_row("Repository", repo_id)
        summary_table.add_row("Quantization", quant)
    summary_table.add_row("Model Type", "[green]Vision[/green]" if is_vision else "[blue]Text[/blue]")
    summary_table.add_row("Service Name", service_name)
    summary_table.add_row("Container Name", container_name)
    summary_table.add_row("Model ID", model_id)
    summary_table.add_row("Models Dir", models_dir)
    summary_table.add_row("llama-swap", "[green]Yes[/green]" if use_swap else "[red]No[/red]")
    summary_table.add_row("Auto-start", "[green]Yes[/green]" if auto_start else "[red]No[/red]")
    
    console.print(summary_table)
    console.print()
    
    proceed = interactive_confirm("[bold yellow]Proceed with these settings?[/bold yellow]", default=True)
    if not proceed:
        console.print("[yellow]Cancelled.[/yellow]")
        sys.exit(0)
    
    return {
        'use_local': use_local,
        'repo_id': repo_id,
        'quant': quant,
        'local_model_path': str(local_model_path) if use_local else None,
        'local_mmproj_path': str(local_mmproj_path) if (use_local and local_mmproj_path) else None,
        'service_name': service_name,
        'container_name': container_name,
        'model_id': model_id,
        'models_dir': models_dir,
        'use_swap': use_swap,
        'auto_start': auto_start,
        'is_vision': is_vision,
        'mmproj_file': mmproj_file
    }


def main():
    parser = argparse.ArgumentParser(
        description='Add a new model to the docker-compose setup',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (default)
  python add_model.py

  # Non-interactive mode
  python add_model.py meta-llama/Meta-Llama-3.1-8B-Instruct-GGUF --quant Q4_K_M

  # Custom name and skip llama-swap
  python add_model.py meta-llama/Meta-Llama-3.1-8B-Instruct-GGUF --name llama-8b --no-swap
        """
    )
    parser.add_argument('repo_id', nargs='?', help='HuggingFace repo ID (optional, will prompt if not provided)')
    parser.add_argument('--quant', '--quantization', default=None,
                       help='Quantization level (default: Q4_K_M)')
    parser.add_argument('--name', help='Custom service/container name (auto-generated if not provided)')
    parser.add_argument('--models-dir', default='./models',
                       help='Models directory (default: ./models)')
    parser.add_argument('--compose', default='docker-compose.yml',
                       help='docker-compose.yml path (default: docker-compose.yml)')
    parser.add_argument('--swap-config', default='config/llama-swap.yaml',
                       help='llama-swap config path (default: config/llama-swap.yaml)')
    parser.add_argument('--no-swap', action='store_true',
                       help='Skip updating llama-swap config')
    parser.add_argument('--no-start', action='store_true',
                       help='Skip starting the service')
    parser.add_argument('--non-interactive', action='store_true',
                       help='Non-interactive mode (requires repo_id argument)')
    
    args = parser.parse_args()
    
    # Interactive mode if no repo_id provided
    if not args.repo_id and not args.non_interactive:
        config = prompt_user()
        use_local = config['use_local']
        repo_id = config.get('repo_id')
        quant = config.get('quant')
        local_model_path = config.get('local_model_path')
        local_mmproj_path = config.get('local_mmproj_path')
        service_name = config['service_name']
        container_name = config['container_name']
        model_id = config['model_id']
        models_dir = config['models_dir']
        use_swap = config['use_swap']
        auto_start = config['auto_start']
        is_vision = config['is_vision']
        mmproj_file = config.get('mmproj_file')
    else:
        # Non-interactive mode (HuggingFace only for now)
        if not args.repo_id:
            console.print("[bold red]Error:[/bold red] repo_id is required in non-interactive mode")
            sys.exit(1)
        
        use_local = False
        repo_id = args.repo_id
        quant = args.quant or 'Q4_K_M'
        local_model_path = None
        local_mmproj_path = None
        
        if args.name:
            service_name = sanitize_name(args.name)
        else:
            model_name = repo_id.split('/')[-1].replace('-GGUF', '').replace('_GGUF', '')
            service_name = f"llamacpp-{sanitize_name(model_name)}"
        
        container_name = service_name.replace('_', '-')
        model_id = service_name.replace('llamacpp-', '')
        models_dir = args.models_dir
        use_swap = not args.no_swap
        auto_start = not args.no_start
        
        # Check for vision model
        mmproj_file = find_mmproj_file(repo_id)
        is_vision = mmproj_file is not None
    
    # Handle local vs HuggingFace models
    if use_local:
        # Process local model
        console.print()
        console.print(Panel.fit(
            "[bold cyan]Processing Local Model...[/bold cyan]",
            border_style="cyan"
        ))
        console.print()
        
        local_model_path_obj = Path(local_model_path).expanduser().resolve()
        models_dir_obj = Path(models_dir).expanduser().resolve()
        
        # Check if model is already in models_dir
        try:
            model_relative = local_model_path_obj.relative_to(models_dir_obj)
            # Model is already in models_dir, use it directly
            model_path = str(local_model_path_obj)
            console.print(f"[green][OK][/green] Model is already in models directory")
        except ValueError:
            # Model is outside models_dir, need to copy it
            console.print(f"[yellow]Model is outside models directory. Copying to {models_dir}...[/yellow]")
            model_name = local_model_path_obj.stem.replace('.gguf', '').replace('_GGUF', '').replace('-GGUF', '')
            target_dir = models_dir_obj / model_name
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / local_model_path_obj.name
            
            _in_operation = True
            try:
                with console.status(f"[bold cyan]Copying {local_model_path_obj.name}...[/bold cyan]", spinner="dots"):
                    import shutil
                    shutil.copy2(local_model_path_obj, target_path)
                    console.print(f"[green][OK][/green] Copied to {target_path}")
            finally:
                _in_operation = False
            
            model_path = str(target_path)
        
        # Handle mmproj if present (only for vision models)
        mmproj_path = None
        if use_local and is_vision and local_mmproj_path and local_mmproj_path != "None":
            local_mmproj_path_obj = Path(local_mmproj_path).expanduser().resolve()
            if not local_mmproj_path_obj.exists():
                console.print(f"[yellow]Warning:[/yellow] MMProj file not found: {local_mmproj_path}")
                console.print(f"[yellow]Continuing without MMProj...[/yellow]")
                mmproj_path = None
            else:
                try:
                    mmproj_relative = local_mmproj_path_obj.relative_to(models_dir_obj)
                    # MMProj is already in models_dir
                    mmproj_path = str(local_mmproj_path_obj)
                    console.print(f"[green][OK][/green] MMProj is already in models directory")
                except ValueError:
                    # MMProj is outside models_dir, copy it
                    console.print(f"[yellow]MMProj is outside models directory. Copying...[/yellow]")
                    model_name = Path(model_path).parent.name
                    target_dir = models_dir_obj / model_name
                    target_path = target_dir / local_mmproj_path_obj.name
                    
                    _in_operation = True
                    try:
                        with console.status(f"[bold cyan]Copying {local_mmproj_path_obj.name}...[/bold cyan]", spinner="dots"):
                            import shutil
                            shutil.copy2(local_mmproj_path_obj, target_path)
                            console.print(f"[green][OK][/green] Copied to {target_path}")
                    finally:
                        _in_operation = False
                    
                    mmproj_path = str(target_path)
    else:
        # HuggingFace flow
        console.print()
        console.print(Panel.fit(
            "[bold cyan]Processing HuggingFace Model...[/bold cyan]",
            border_style="cyan"
        ))
        console.print()
        
        # Find model file
        _in_operation = True
        try:
            with console.status("[bold cyan]Finding model file...[/bold cyan]", spinner="dots"):
                model_file = find_model_file(repo_id, quant)
                if not model_file:
                    console.print(f"[bold red]Error:[/bold red] Could not find model file with quantization [cyan]{quant}[/cyan]")
                    console.print("[yellow]Warning:[/yellow] Available quantizations may differ. Try listing files in the repo.")
                    sys.exit(1)
        finally:
            _in_operation = False
        
        console.print(f"[green][OK][/green] Found model file: [cyan]{model_file}[/cyan]")
        
        # Prompt for download directory
        model_name = repo_id.split('/')[-1].replace('-GGUF', '').replace('_GGUF', '')
        download_dir_name = prompt_download_directory(models_dir, model_name)
        
        # Download model
        console.print()
        console.print(Panel(
            "[bold]Downloading Model[/bold]\n\n"
            f"Downloading to: [cyan]{download_dir_name}[/cyan]\n"
            "This may take a while depending on model size...",
            title="[cyan]Download[/cyan]",
            border_style="cyan"
        ))
        console.print()
        
        model_path, mmproj_path = download_model(
            repo_id, model_file, mmproj_file,
            models_dir, download_dir_name
        )
        
        console.print(f"[green][OK][/green] Model downloaded: [cyan]{Path(model_path).name}[/cyan]")
        if mmproj_path:
            console.print(f"[green][OK][/green] MMProj downloaded: [cyan]{Path(mmproj_path).name}[/cyan]")
    
    # Add to docker-compose
    console.print()
    _in_operation = True
    try:
        with console.status("[bold cyan]Adding service to docker-compose.yml...[/bold cyan]", spinner="dots"):
            # Expand tilde in models_dir before passing to add_service_to_compose
            models_dir_expanded = str(Path(models_dir).expanduser().resolve())
            add_service_to_compose(
                args.compose, service_name, container_name,
                model_path, mmproj_path, models_dir_expanded
            )
    finally:
        _in_operation = False
    
    # Update llama-swap if requested
    if use_swap:
        console.print()
        _in_operation = True
        try:
            with console.status("[bold cyan]Updating llama-swap config...[/bold cyan]", spinner="dots"):
                update_llama_swap(args.swap_config, model_id, service_name)
        finally:
            _in_operation = False
    
    # Start service
    if auto_start:
        console.print()
        _in_operation = True
        try:
            with console.status(f"[bold cyan]Starting service '{service_name}'...[/bold cyan]", spinner="dots"):
                subprocess.run(['docker', 'compose', '-f', args.compose, 'up', '-d', service_name], 
                             check=True, capture_output=True)
            console.print(f"[green][OK][/green] Service '[cyan]{service_name}[/cyan]' started")
        finally:
            _in_operation = False
    
    # Final summary
    console.print()
    console.print(Panel.fit(
        "[bold green]Model Added Successfully![/bold green]",
        border_style="green"
    ))
    console.print()
    
    connection_table = Table(title="[bold green]Connection Details[/bold green]", box=box.ROUNDED, show_header=False)
    connection_table.add_column("Type", style="cyan", width=15)
    connection_table.add_column("URL", style="white")
    
    connection_table.add_row("Direct", f"http://{service_name}:8001/v1")
    if use_swap:
        connection_table.add_row("Proxy", f"http://llama-swap:8080/v1")
        connection_table.add_row("Model ID", f"[cyan]{model_id}[/cyan]")
    
    console.print(connection_table)
    console.print()
    
    info_table = Table(box=box.ROUNDED, show_header=False)
    info_table.add_column("Property", style="cyan", width=15)
    info_table.add_column("Value", style="white")
    info_table.add_row("Container", container_name)
    info_table.add_row("Service", service_name)
    
    console.print(info_table)
    console.print()


if __name__ == '__main__':
    main()
