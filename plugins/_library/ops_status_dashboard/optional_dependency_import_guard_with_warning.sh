# ── SNIPPET: ops_status_dashboard/optional_dependency_import_guard_with_warning ─
# Scheduler:   any
# Tool:        auto3d
# Tested:      purdue_standby_auto3d_auto_batch
# Notes: Keep this pattern when deploying to heterogeneous nodes/environments.
# ────────────────────────────────────────────────────────────

try:
    # Auto3D imports (GPU-enabled stage)
    import Auto3D
    from Auto3D.auto3D import options as auto3d_options
    from Auto3D.auto3D import main as auto3d_main
    _AUTO3D_AVAILABLE = True
except Exception:
    _AUTO3D_AVAILABLE = False
