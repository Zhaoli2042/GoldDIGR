#!/usr/bin/env python3
"""
plugin.py – CLI entry point for golddigr plugin commands.

Runs on the HOST (no container needed). Only requires: python3, pyyaml, requests.

Usage:
    python plugin.py develop <path>      # incremental test-driven development
    python plugin.py catalog <path>      # catalog into knowledge base
    python plugin.py diagnose <name>     # LLM failure diagnosis
    python plugin.py probe               # detect cluster infrastructure
    python plugin.py list                # list registered plugins
    python plugin.py init <path>         # (legacy) generate plugin.yaml + glue
    python plugin.py pilot-loop <name>   # (legacy) generate pilot loop script
"""

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

from pipeline import setup_logging


# ═══════════════════════════════════════════════════════════════════════
# Project root detection
# ═══════════════════════════════════════════════════════════════════════

def _get_project_root() -> Path:
    """Return the project root directory."""
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "data").exists() or (script_dir / "plugins").exists():
        return script_dir
    return Path.cwd()


PROJECT_ROOT = _get_project_root()


# ═══════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════

def _resolve_llm_config(args):
    """Resolve LLM provider/model from args > config.yaml > defaults."""
    provider = getattr(args, "provider", None)
    model = getattr(args, "model", None)

    if provider is None or model is None:
        try:
            with open("config.yaml") as f:
                cfg = yaml.safe_load(f)
            llm_cfg = cfg.get("llm", {})
            if provider is None:
                raw = llm_cfg.get("provider", "openai")
                m = re.match(r"\$\{(\w+):-(\w+)\}", str(raw))
                provider = os.environ.get(m.group(1), m.group(2)) if m else str(raw)
            if model is None:
                raw = llm_cfg.get("model", "gpt-4o")
                m = re.match(r"\$\{(\w+):-([^}]+)\}", str(raw))
                model = os.environ.get(m.group(1), m.group(2)) if m else str(raw)
        except Exception:
            provider = provider or "openai"
            model = model or "gpt-4o"

    return provider, model


def _find_plugin_dir(name: str) -> Path:
    """Find a plugin by name, directory name, or direct path."""
    from pipeline.plugins.registry import discover_plugins, load_manifest

    # Direct path (absolute or relative)
    candidate = Path(name)
    if candidate.is_dir():
        return candidate.resolve()

    plugins_root = Path("plugins")

    # Search by manifest name or directory name
    for p in discover_plugins(plugins_root):
        m = load_manifest(p)
        if m["name"] == name or p.name == name:
            return p

    # Check plugins/<name> even without plugin.yaml
    direct = plugins_root / name
    if direct.is_dir():
        return direct

    print(f"Plugin '{name}' not found. Run 'plugin list' to see available plugins.")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="golddigr plugin commands (runs on host, no container needed)",
        prog="golddigr plugin",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="action")

    # ── develop ───────────────────────────────────────────────────────
    dev = sub.add_parser("develop", help="Incremental test-driven plugin development")
    dev.add_argument("name", help="Plugin name or path")
    dev.add_argument("--provider", default=None, help="LLM provider")
    dev.add_argument("--model", default=None, help="LLM model")
    dev.add_argument("--force", action="store_true",
                     help="Regenerate glue/ even if it already exists")

    # ── catalog ───────────────────────────────────────────────────────
    cat = sub.add_parser("catalog", help="Catalog a plugin into the knowledge base")
    cat.add_argument("name", help="Plugin name or path")
    cat.add_argument("--provider", default=None, help="LLM provider")
    cat.add_argument("--model", default=None, help="LLM model")
    cat.add_argument("--extract-snippets", action="store_true",
                     help="Extract reusable code snippets into _library/")
    cat.add_argument("-y", "--yes", action="store_true",
                     help="Accept all prompts (non-interactive)")

    # ── diagnose ──────────────────────────────────────────────────────
    diag = sub.add_parser("diagnose", help="LLM-powered failure diagnosis")
    diag.add_argument("name", help="Plugin name")
    diag.add_argument("--pilot-dir", type=Path, default=None,
                      help="Path to pilot results directory")
    diag.add_argument("--results-dir", type=Path, default=None,
                      help="Path to production results (debug mode)")
    diag.add_argument("--mode", choices=["pilot", "debug"], default="pilot")
    diag.add_argument("--provider", default=None, help="LLM provider")
    diag.add_argument("--model", default=None, help="LLM model")
    diag.add_argument("--auto-fix", action="store_true",
                      help="Auto-apply fixes for glue issues")

    # ── probe ─────────────────────────────────────────────────────────
    sub.add_parser("probe", help="Auto-detect target machine infrastructure")

    # ── list ──────────────────────────────────────────────────────────
    sub.add_parser("list", help="List registered plugins")

    # ── init (legacy) ─────────────────────────────────────────────────
    init = sub.add_parser("init", help="(Legacy) LLM-powered plugin.yaml + glue generator")
    init.add_argument("path", type=Path, help="Path to plugin directory")
    init.add_argument("--provider", default=None, help="LLM provider")
    init.add_argument("--model", default=None, help="LLM model")
    init.add_argument("-y", "--yes", action="store_true")

    # ── pilot-loop (legacy) ───────────────────────────────────────────
    loop = sub.add_parser("pilot-loop", help="(Legacy) Generate pilot loop script")
    loop.add_argument("name", help="Plugin name")
    loop.add_argument("--n-jobs", type=int, default=1)
    loop.add_argument("--max-iterations", type=int, default=5)
    loop.add_argument("--poll-interval", type=int, default=60)
    loop.add_argument("--provider", default=None, help="LLM provider")
    loop.add_argument("--model", default=None, help="LLM model")

    # ── pilot (legacy) ────────────────────────────────────────────────
    pilot = sub.add_parser("pilot", help="(Legacy) Run pilot test")
    pilot.add_argument("name", help="Plugin name")
    pilot.add_argument("--n-jobs", type=int, default=3)
    pilot.add_argument("--poll-interval", type=int, default=60)
    pilot.add_argument("--max-wait", type=int, default=7200)
    pilot.add_argument("--auto-fix", action="store_true")
    pilot.add_argument("--prep-only", action="store_true")
    pilot.add_argument("--pilot-dir", type=Path, default=None)
    pilot.add_argument("--provider", default=None)
    pilot.add_argument("--model", default=None)

    # ── package ───────────────────────────────────────────────────────
    pkg = sub.add_parser("package", help="Build HPC submission packages")
    pkg.add_argument("name", help="Plugin name")
    pkg.add_argument("--cluster", type=Path, default=Path("cluster.yaml"))
    pkg.add_argument("--output", type=Path,
                     default=PROJECT_ROOT / "data" / "output" / "packages")
    pkg.add_argument("--article", type=int, default=None)

    # ── register ──────────────────────────────────────────────────────
    reg = sub.add_parser("register", help="Validate and register a plugin")
    reg.add_argument("path", type=Path, help="Path to plugin directory")

    # ── launch ────────────────────────────────────────────────────────
    launch = sub.add_parser("launch", help="Full launch (after pilot passes)")
    launch.add_argument("name", help="Plugin name")
    launch.add_argument("--force", action="store_true")

    # ── port ──────────────────────────────────────────────────────────
    port = sub.add_parser("port", help="Port workflow to a different scheduler")
    port.add_argument("name", help="Plugin name")
    port.add_argument("--target", required=True,
                      choices=["slurm", "htcondor", "sge", "pbs", "local"])
    port.add_argument("--template", type=Path, default=None)
    port.add_argument("--provider", default=None)
    port.add_argument("--model", default=None)

    args = parser.parse_args()
    setup_logging(getattr(args, "verbose", False), log_filename="plugin.log")

    action = args.action
    if action is None:
        parser.print_help()
        sys.exit(1)

    # ── Dispatch ──────────────────────────────────────────────────────
    if action == "develop":
        _do_develop(args)
    elif action == "catalog":
        _do_catalog(args)
    elif action == "diagnose":
        _do_diagnose(args)
    elif action == "probe":
        _do_probe()
    elif action == "list":
        _do_list()
    elif action == "init":
        _do_init(args)
    elif action == "pilot-loop":
        _do_pilot_loop(args)
    elif action == "pilot":
        _do_pilot(args)
    elif action == "package":
        _do_package(args)
    elif action == "register":
        _do_register(args)
    elif action == "launch":
        _do_launch(args)
    elif action == "port":
        _do_port(args)
    else:
        parser.print_help()
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════
# Command implementations
# ═══════════════════════════════════════════════════════════════════════

def _do_develop(args):
    from pipeline.plugins.develop import develop_plugin

    candidate = Path(args.name)
    if candidate.is_dir():
        plugin_dir = candidate.resolve()
    else:
        fallback = Path("plugins") / args.name
        if fallback.is_dir():
            plugin_dir = fallback.resolve()
        else:
            print(f"❌ Directory not found: {args.name}")
            sys.exit(1)

    provider, model = _resolve_llm_config(args)

    result = develop_plugin(
        plugin_dir=plugin_dir,
        plugins_root=Path("plugins"),
        provider=provider,
        model=model,
        force=getattr(args, 'force', False),
    )

    if result.get("status") in ("glue_exists", "empty_plugin"):
        sys.exit(1 if result["status"] == "empty_plugin" else 0)


def _do_catalog(args):
    from pipeline.plugins.catalog import catalog_plugin, extract_snippets

    candidate = Path(args.name)
    if candidate.is_dir():
        plugin_dir = candidate.resolve()
    else:
        try:
            plugin_dir = _find_plugin_dir(args.name)
        except SystemExit:
            fallback = Path("plugins") / args.name
            if fallback.is_dir():
                plugin_dir = fallback.resolve()
            else:
                print(f"❌ Directory not found: {args.name}")
                sys.exit(1)

    provider, model = _resolve_llm_config(args)
    plugins_root = Path("plugins")
    non_interactive = getattr(args, 'yes', False)

    success = catalog_plugin(
        plugin_dir=plugin_dir,
        plugins_root=plugins_root,
        provider=provider,
        model=model,
        non_interactive=non_interactive,
    )

    if not success:
        sys.exit(1)

    if getattr(args, 'extract_snippets', False):
        extract_snippets(
            plugin_dir=plugin_dir,
            plugins_root=plugins_root,
            provider=provider,
            model=model,
            non_interactive=non_interactive,
        )


def _do_diagnose(args):
    from pipeline.plugins.diagnose import diagnose_results

    plugin_dir = _find_plugin_dir(args.name)
    provider, model = _resolve_llm_config(args)

    if args.results_dir:
        from pipeline.plugins.diagnose import diagnose_production
        diagnose_production(plugin_dir, args.results_dir)
        return

    # Find pilot directory
    pilot_dir = args.pilot_dir
    if pilot_dir is None:
        pilots_root = PROJECT_ROOT / "data" / "output" / "pilots" / plugin_dir.name
        if not pilots_root.is_dir():
            pilots_root = Path("data") / "output" / "pilots" / plugin_dir.name
        if pilots_root.is_dir():
            latest = pilots_root / "latest"
            if latest.is_symlink() or latest.exists():
                pilot_dir = latest.resolve()
            else:
                subdirs = sorted([d for d in pilots_root.iterdir() if d.is_dir()],
                                 key=lambda d: d.name, reverse=True)
                if subdirs:
                    pilot_dir = subdirs[0]

    if pilot_dir is None or not Path(pilot_dir).is_dir():
        print(f"❌ No pilot directory found for '{args.name}'.")
        sys.exit(1)

    report = diagnose_results(
        pilot_dir=pilot_dir,
        provider=provider,
        model=model,
        mode=args.mode,
        auto_fix=args.auto_fix,
    )

    if report.get("error"):
        sys.exit(1)


def _do_probe():
    from pipeline.plugins.probe import probe_infrastructure, format_probe_report

    # Force fresh probe
    import pipeline.plugins.probe as probe_mod
    original_load = probe_mod.load_saved_probe
    probe_mod.load_saved_probe = lambda: None
    try:
        infra = probe_infrastructure()
    finally:
        probe_mod.load_saved_probe = original_load

    print(format_probe_report(infra))

    probe_path = PROJECT_ROOT / "data" / "output" / "infrastructure_probe.yaml"
    probe_path.parent.mkdir(parents=True, exist_ok=True)
    probe_path.write_text(yaml.dump(infra, default_flow_style=False, sort_keys=False))
    print(f"\n   Saved to: {probe_path}")


def _do_list():
    from pipeline.plugins.registry import discover_plugins, load_manifest

    plugins_root = Path("plugins")
    if not plugins_root.is_dir():
        print("No plugins/ directory found.")
        return

    plugins = discover_plugins(plugins_root)
    if not plugins:
        print("No plugins found in plugins/")
        return

    print(f"\n{'Name':<40s} {'Version':<10s} {'Stages':<8s} Path")
    print("─" * 80)
    for p in sorted(plugins, key=lambda x: x.name):
        m = load_manifest(p)
        name = m.get("name", p.name)
        version = m.get("version", "?")
        stages = len(m.get("stages", []))
        print(f"{name:<40s} {version:<10s} {stages:<8d} {p}")
    print()


def _do_init(args):
    from pipeline.plugins.initializer import init_plugin

    plugin_path = args.path.resolve()
    provider, model = _resolve_llm_config(args)
    non_interactive = getattr(args, 'yes', False)

    success = init_plugin(
        plugin_dir=plugin_path,
        plugins_root=Path("plugins"),
        provider=provider,
        model=model,
        non_interactive=non_interactive,
    )
    if not success:
        sys.exit(1)


def _do_pilot_loop(args):
    from pipeline.plugins.pilot import generate_pilot_loop

    plugin_dir = _find_plugin_dir(args.name)
    provider, model = _resolve_llm_config(args)
    xyz_root = PROJECT_ROOT / "data" / "output" / "xyz"

    result = generate_pilot_loop(
        plugin_dir=plugin_dir,
        xyz_root=xyz_root,
        n_jobs=args.n_jobs,
        max_iterations=args.max_iterations,
        poll_interval=args.poll_interval,
        provider=provider or "openai",
        model=model or "gpt-4o",
    )

    if result.get("error"):
        sys.exit(1)


def _do_pilot(args):
    from pipeline.plugins.pilot import run_pilot

    plugin_dir = _find_plugin_dir(args.name)
    provider, model = _resolve_llm_config(args)
    xyz_root = PROJECT_ROOT / "data" / "output" / "xyz"

    result = run_pilot(
        plugin_dir=plugin_dir,
        xyz_root=xyz_root,
        n_jobs=args.n_jobs,
        poll_interval=args.poll_interval,
        max_wait=args.max_wait,
        auto_diagnose=args.auto_fix,
        prep_only=getattr(args, 'prep_only', False),
        resume_dir=getattr(args, 'pilot_dir', None),
        provider=provider or "openai",
        model=model or "gpt-4o",
    )

    if result.get("error"):
        sys.exit(1)


def _do_package(args):
    from pipeline.plugins.registry import discover_plugins, load_manifest
    from pipeline.plugins.packager import package_article, package_all_articles

    plugin_dir = _find_plugin_dir(args.name)
    xyz_root = PROJECT_ROOT / "data" / "output" / "xyz"
    output_dir = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.article is not None:
        # Package a single article — resolve DOI path from DB
        from pipeline.job_db import JobDB
        from pipeline.metadata import doi_to_path
        db_path = PROJECT_ROOT / "data" / "db" / "pipeline.db"
        db = JobDB(str(db_path))
        job = db.get_job(args.article)
        db.close()
        if job and job["doi"]:
            article_dir = xyz_root / doi_to_path(job["doi"])
        else:
            article_dir = xyz_root / str(args.article)
        result = package_article(
            article_id=args.article,
            xyz_dir=article_dir,
            plugin_dir=plugin_dir,
            cluster_yaml=args.cluster,
            output_dir=output_dir,
        )
        if result:
            print(f"Packaged article {args.article} → {result}")
        else:
            print(f"No XYZ files found for article {args.article}")
    else:
        # Package all articles
        tarballs = package_all_articles(
            pipeline_db_path=PROJECT_ROOT / "data" / "db" / "pipeline.db",
            xyz_root=xyz_root,
            plugin_dir=plugin_dir,
            cluster_yaml=args.cluster,
            output_dir=output_dir,
        )
        print(f"Packaged {len(tarballs)} articles")


def _do_register(args):
    from pipeline.plugins.registry import discover_plugins, load_manifest

    plugin_dir = args.path.resolve()
    manifest = load_manifest(plugin_dir)

    print(f"\n✅ Plugin registered: {manifest['name']}")
    print(f"   Path:       {plugin_dir}")
    print(f"   Stages:     {len(manifest.get('stages', []))}")
    for i, s in enumerate(manifest.get("stages", []), 1):
        print(f"   {i}. {s.get('name', '?'):<20s} ({s.get('type', '?')})")


def _do_launch(args):
    print(f"🚀 Launch not yet implemented for host-side execution.")
    print(f"   Use 'develop' to generate and test scripts, then run manually.")


def _do_port(args):
    from pipeline.plugins.porter import port_plugin

    plugin_dir = _find_plugin_dir(args.name)
    provider, model = _resolve_llm_config(args)

    port_plugin(
        plugin_dir=plugin_dir,
        target_scheduler=args.target,
        target_template=args.template,
        provider=provider or "openai",
        model=model or "gpt-4o",
    )


if __name__ == "__main__":
    main()
