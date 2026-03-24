"""
CAM Interactive Setup

Rich-based interactive setup for Collective Agent Memory.
Handles agent detection, sync configuration, and initial indexing.
"""

import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional, List, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import print as rprint

console = Console()

# Models required by CAM
REQUIRED_MODELS = [
    ("sentence-transformers/all-MiniLM-L6-v2", "embeddings"),
    ("fastino/gliner2-base-v1", "entity extraction"),
]


def get_hostname() -> str:
    """Get machine hostname."""
    import socket
    return socket.gethostname().split('.')[0]


def check_hf_token() -> bool:
    """Check if HF_TOKEN is set."""
    return bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"))


def check_model_cached(model_id: str) -> bool:
    """Check if a HuggingFace model is already cached."""
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
    model_dir = cache_dir / f"models--{model_id.replace('/', '--')}"

    # Check if model directory exists and has snapshots
    if model_dir.exists():
        snapshots_dir = model_dir / "snapshots"
        if snapshots_dir.exists() and any(snapshots_dir.iterdir()):
            return True
    return False


def download_models(non_interactive: bool = False) -> bool:
    """Download required ML models if not cached."""
    from huggingface_hub import snapshot_download

    missing_models = []
    for model_id, purpose in REQUIRED_MODELS:
        if not check_model_cached(model_id):
            missing_models.append((model_id, purpose))

    if not missing_models:
        console.print("[green]✓[/green] All models cached")
        return True

    # Check HF_TOKEN
    has_token = check_hf_token()
    if not has_token:
        console.print()
        console.print("[yellow]Tip:[/yellow] Set HF_TOKEN for faster downloads")
        console.print("[dim]  export HF_TOKEN=hf_xxx  # Get token from huggingface.co/settings/tokens[/dim]")
        console.print()

    console.print(f"[bold]Downloading {len(missing_models)} model(s)...[/bold]")

    for model_id, purpose in missing_models:
        console.print(f"  Downloading [cyan]{model_id}[/cyan] ({purpose})...")
        try:
            snapshot_download(
                repo_id=model_id,
                local_files_only=False,
            )
            console.print(f"  [green]✓[/green] {model_id}")
        except Exception as e:
            console.print(f"  [red]✗[/red] {model_id}: {e}")
            return False

    return True


def detect_agents() -> List[Tuple[str, Path, int]]:
    """
    Detect installed agents and count their sessions.
    Returns list of (agent_name, path, session_count).
    """
    agents = []

    # Claude Code
    claude_dir = Path.home() / ".claude" / "projects"
    if claude_dir.exists():
        count = len(list(claude_dir.glob("**/*.jsonl")))
        if count > 0:
            agents.append(("Claude Code", claude_dir, count))

    # Cursor
    cursor_dir = Path.home() / ".cursor" / "projects"
    if cursor_dir.exists():
        count = len(list(cursor_dir.glob("**/agent-transcripts/**/*.jsonl")))
        if count > 0:
            agents.append(("Cursor", cursor_dir, count))

    # OpenClaw
    openclaw_dir = Path.home() / ".openclaw" / "agents"
    if openclaw_dir.exists():
        count = len(list(openclaw_dir.glob("**/*.jsonl")))
        if count > 0:
            agents.append(("OpenClaw", openclaw_dir, count))

    # Codex CLI
    codex_dir = Path.home() / ".codex" / "sessions"
    if codex_dir.exists():
        count = len(list(codex_dir.glob("*.jsonl")))
        if count > 0:
            agents.append(("Codex CLI", codex_dir, count))

    return agents


def check_github_access() -> Optional[str]:
    """Check if gh CLI is authenticated and return username."""
    if not shutil.which("gh"):
        return None

    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return None

    result = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def create_github_repo(repo: str) -> bool:
    """Create a private GitHub repo if it doesn't exist."""
    # Check if repo exists
    result = subprocess.run(
        ["gh", "repo", "view", repo],
        capture_output=True
    )
    if result.returncode == 0:
        return True  # Already exists

    # Create it
    result = subprocess.run(
        ["gh", "repo", "create", repo, "--private",
         "--description", "Collective Agent Memory - synced session segments"],
        capture_output=True,
        text=True
    )
    return result.returncode == 0


def setup_workspace(sync_repo: Optional[str], machine_id: str) -> Path:
    """Initialize the workspace directory."""
    workspace_dir = Path.home() / ".cam" / "sessions"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    if sync_repo:
        os.chdir(workspace_dir)

        # Initialize git if needed
        if not (workspace_dir / ".git").exists():
            subprocess.run(["git", "init", "-q"], capture_output=True)
            subprocess.run(
                ["git", "remote", "add", "origin", f"https://github.com/{sync_repo}.git"],
                capture_output=True
            )

        # Try to pull existing content
        subprocess.run(["git", "fetch", "origin", "main"], capture_output=True)
        subprocess.run(["git", "checkout", "-B", "main", "origin/main"], capture_output=True)

    return workspace_dir


def write_config(sync_repo: Optional[str], workspace_dir: Path, machine_id: str):
    """Write CAM configuration file."""
    config_dir = Path.home() / ".cam"
    config_dir.mkdir(parents=True, exist_ok=True)

    config_file = config_dir / "config"

    lines = ["# CAM Configuration"]
    if sync_repo:
        lines.append(f"CAM_SYNC_REPO={sync_repo}")
    lines.append(f"CAM_WORKSPACE_DIR={workspace_dir}")
    lines.append(f"CAM_MACHINE_ID={machine_id}")

    config_file.write_text("\n".join(lines) + "\n")


def install_skill(agent: str) -> bool:
    """Install CAM skill for an agent."""
    cam_bin = shutil.which("cam") or str(Path.home() / ".local" / "bin" / "cam")
    if not os.path.exists(cam_bin):
        return False

    result = subprocess.run(
        [cam_bin, "skill", "install", "-a", agent.lower().replace(" ", "")],
        capture_output=True
    )
    return result.returncode == 0


def install_daemon(sync_repo: str, workspace_dir: Path, machine_id: str) -> bool:
    """Install the background sync daemon."""
    import platform
    system = platform.system()

    cam_bin = shutil.which("cam") or str(Path.home() / ".local" / "bin" / "cam")

    if system == "Darwin":
        plist_dir = Path.home() / "Library" / "LaunchAgents"
        plist_dir.mkdir(parents=True, exist_ok=True)

        plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>net.julianfleck.cam</string>
    <key>ProgramArguments</key>
    <array>
        <string>{cam_bin}</string>
        <string>daemon</string>
        <string>run</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>CAM_SYNC_REPO</key>
        <string>{sync_repo}</string>
        <key>CAM_WORKSPACE_DIR</key>
        <string>{workspace_dir}</string>
        <key>CAM_MACHINE_ID</key>
        <string>{machine_id}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:{Path.home()}/.local/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{Path.home()}/Library/Logs/cam.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/Library/Logs/cam.error.log</string>
</dict>
</plist>'''

        plist_path = plist_dir / "net.julianfleck.cam.plist"
        plist_path.write_text(plist_content)

        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        result = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)
        return result.returncode == 0

    elif system == "Linux":
        service_dir = Path.home() / ".config" / "systemd" / "user"
        service_dir.mkdir(parents=True, exist_ok=True)

        service_content = f'''[Unit]
Description=Collective Agent Memory Daemon
After=network.target

[Service]
Type=simple
ExecStart={cam_bin} daemon run
Environment="CAM_SYNC_REPO={sync_repo}"
Environment="CAM_WORKSPACE_DIR={workspace_dir}"
Environment="CAM_MACHINE_ID={machine_id}"
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target'''

        service_path = service_dir / "cam.service"
        service_path.write_text(service_content)

        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        result = subprocess.run(
            ["systemctl", "--user", "enable", "--now", "cam.service"],
            capture_output=True
        )
        return result.returncode == 0

    return False


def run_index(workspace_dir: Path, foreground: bool = True) -> bool:
    """Run session indexing."""
    cam_bin = shutil.which("cam") or str(Path.home() / ".local" / "bin" / "cam")

    env = os.environ.copy()
    env["CAM_WORKSPACE_DIR"] = str(workspace_dir)

    if foreground:
        # Run in foreground with output visible
        result = subprocess.run([cam_bin, "index"], env=env)
        return result.returncode == 0
    else:
        # Run in background
        subprocess.Popen(
            [cam_bin, "index"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True


def run_init(non_interactive: bool = False):
    """Run the interactive CAM setup."""
    machine_id = get_hostname()

    # Header
    console.print()
    console.print(Panel.fit(
        "[bold]CAM - Collective Agent Memory[/bold]\n"
        "Search across all your AI coding sessions",
        border_style="blue"
    ))
    console.print()

    # Detect agents
    console.print("[bold]Detecting agents...[/bold]")
    agents = detect_agents()

    if agents:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Agent")
        table.add_column("Sessions", justify="right")
        table.add_column("Location")

        total_sessions = 0
        for name, path, count in agents:
            table.add_row(name, str(count), f"~/{path.relative_to(Path.home())}")
            total_sessions += count

        console.print(table)
        console.print(f"\n[green]{total_sessions} total sessions found[/green]")
    else:
        console.print("[yellow]No agent sessions found yet[/yellow]")

    console.print()

    # Install skills
    if agents:
        console.print("[bold]Installing skills...[/bold]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            for name, _, _ in agents:
                task = progress.add_task(f"Installing {name} skill...", total=None)
                agent_key = name.lower().replace(" ", "").replace("cli", "")
                if install_skill(agent_key):
                    console.print(f"  [green]✓[/green] {name}")
                else:
                    console.print(f"  [yellow]-[/yellow] {name} (skipped)")
                progress.remove_task(task)
        console.print()

    # Check GitHub access and ask about sync
    sync_repo = None

    gh_user = check_github_access()

    if gh_user:
        console.print(f"[dim]GitHub: logged in as {gh_user}[/dim]")
        console.print()

        if non_interactive:
            # Auto-enable sync with default repo
            sync_repo = f"{gh_user}/agent-memory"
            console.print(f"[dim]Sync enabled: {sync_repo}[/dim]")
        else:
            setup_sync = Confirm.ask(
                "Enable cross-machine sync via GitHub?",
                default=True
            )

            if setup_sync:
                default_repo = f"{gh_user}/agent-memory"
                sync_repo = Prompt.ask(
                    "Sync repository",
                    default=default_repo
                )
                console.print()
    elif not non_interactive:
        console.print("[dim]GitHub CLI not configured - sync disabled[/dim]")
        console.print("[dim]Run 'gh auth login' then 'cam init' to enable sync[/dim]")
        console.print()

    # Setup workspace
    workspace_dir = Path.home() / ".cam" / "sessions"

    if sync_repo:
        console.print("[bold]Setting up sync...[/bold]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            # Create repo if needed
            task = progress.add_task("Checking repository...", total=None)
            if create_github_repo(sync_repo):
                console.print(f"  [green]✓[/green] Repository: {sync_repo}")
            else:
                console.print(f"  [red]✗[/red] Failed to create repository")
                sync_repo = None
            progress.remove_task(task)

            if sync_repo:
                # Setup workspace
                task = progress.add_task("Initializing workspace...", total=None)
                workspace_dir = setup_workspace(sync_repo, machine_id)
                console.print(f"  [green]✓[/green] Workspace: ~/.cam/sessions/")
                progress.remove_task(task)

                # Write config
                task = progress.add_task("Writing config...", total=None)
                write_config(sync_repo, workspace_dir, machine_id)
                console.print(f"  [green]✓[/green] Config: ~/.cam/config")
                progress.remove_task(task)

        console.print()

        # Ask about daemon (auto-install in non-interactive mode)
        start_daemon = non_interactive or Confirm.ask(
            "Start background sync daemon?",
            default=True
        )

        if start_daemon:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True
            ) as progress:
                task = progress.add_task("Installing daemon...", total=None)
                if install_daemon(sync_repo, workspace_dir, machine_id):
                    import platform
                    if platform.system() == "Darwin":
                        console.print(f"  [green]✓[/green] Daemon running (launchd)")
                        console.print(f"  [dim]Logs: ~/Library/Logs/cam.log[/dim]")
                    else:
                        console.print(f"  [green]✓[/green] Daemon running (systemd)")
                        console.print(f"  [dim]Logs: journalctl --user -u cam -f[/dim]")
                else:
                    console.print(f"  [yellow]-[/yellow] Daemon not installed")
                progress.remove_task(task)
            console.print()
    else:
        # Local only setup
        workspace_dir.mkdir(parents=True, exist_ok=True)
        write_config(None, workspace_dir, machine_id)

    # Download models if needed
    console.print("[bold]Checking ML models...[/bold]")
    download_models(non_interactive=non_interactive)
    console.print()

    # Ask about initial indexing
    total_sessions = sum(count for _, _, count in agents)

    if total_sessions > 0:
        console.print(f"[bold]Ready to index {total_sessions} sessions[/bold]")
        console.print()

        if non_interactive:
            # Auto-start indexing in background
            console.print("[dim]Starting indexing in background...[/dim]")
            run_index(workspace_dir, foreground=False)
            console.print("[green]Indexing started in background[/green]")
            console.print("[dim]Check progress with: cam status[/dim]")
        else:
            run_now = Confirm.ask("Index sessions now?", default=True)

            if run_now:
                run_in_bg = Confirm.ask(
                    "Run in background?",
                    default=False
                )

                console.print()

                if run_in_bg:
                    console.print("[dim]Starting indexing in background...[/dim]")
                    run_index(workspace_dir, foreground=False)
                    console.print("[green]Indexing started in background[/green]")
                    console.print("[dim]Check progress with: cam status[/dim]")
                else:
                    console.print("[bold]Indexing sessions...[/bold]")
                    console.print()
                    run_index(workspace_dir, foreground=True)
            else:
                console.print()
                console.print("[dim]Run 'cam index' to index sessions later[/dim]")

    # Final summary
    console.print()
    console.print(Panel.fit(
        "[bold green]Setup complete![/bold green]\n\n"
        "[bold]Search:[/bold]\n"
        "  cam search \"query\"   Keyword (fast)\n"
        "  cam vsearch \"query\"  Semantic\n"
        "  cam query \"query\"    Hybrid (best)\n\n"
        "[bold]Other:[/bold]\n"
        "  cam status           Show status\n"
        + (f"  cam sync             Sync now\n" if sync_repo else "  cam index            Index sessions\n"),
        border_style="green"
    ))
    console.print()


if __name__ == "__main__":
    run_init()
