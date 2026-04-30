"""``signal-trck serve`` — boot the FastAPI web UI on localhost.

Hardcoded ``127.0.0.1`` bind per Decision 16 — no escape hatch. A user who
needs tailnet/LAN access can edit the source. Localhost-only is the
security boundary for this personal-tool design.

Two modes:

- **Dev**: ``signal-trck serve --reload`` enables uvicorn auto-reload and
  also sets ``SIGNAL_TRCK_DEV=1`` so the FastAPI app turns on the CORS
  allow-list for ``http://localhost:5173`` (Vite dev server).
- **Prod**: ``signal-trck serve`` boots without reload; assumes the
  frontend has been built (``npm run build``) and the SPA assets live in
  ``web/dist/``. Currently the prod static-mount path is wired via uvicorn
  serving the ASGI app only; static-asset mounting is a Phase B.2 polish
  task once the UI exists.
"""

from __future__ import annotations

import os

import typer
import uvicorn


def serve(
    port: int = typer.Option(8000, "--port", "-p", help="Listen port (default 8000)"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code change (dev mode)"),
) -> None:
    """Start the local web server. Bound to 127.0.0.1 only (no LAN exposure).

    Dev-mode (``--reload``) also enables CORS for the Vite dev server at
    ``http://localhost:5173``. Prod mode (no flag) disables CORS — the
    frontend must be served from the same origin.
    """
    if reload:
        os.environ["SIGNAL_TRCK_DEV"] = "1"
    typer.echo(f"signal-trck serve → http://127.0.0.1:{port}{' (reload)' if reload else ''}")
    uvicorn.run(
        "signal_trck.api.app:app",
        host="127.0.0.1",
        port=port,
        reload=reload,
        log_config=None,
    )
