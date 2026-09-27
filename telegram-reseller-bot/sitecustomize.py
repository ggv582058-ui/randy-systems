from __future__ import annotations

import os
import sys


# Render starts this service with `python bot.py`. The pricing/history additions
# live in run_with_cert_prices.py, so transparently route only that entrypoint
# through the wrapper without changing Render's service configuration.
if os.getenv("RANDY_CERT_WRAPPER_ACTIVE") != "1":
    script = os.path.basename(sys.argv[0] or "")
    if script == "bot.py":
        os.environ["RANDY_CERT_WRAPPER_ACTIVE"] = "1"
        wrapper = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "run_with_cert_prices.py")
        os.execv(sys.executable, [sys.executable, wrapper, *sys.argv[1:]])
else:
    # The wrapper process imports this before executing its main file. Loading the
    # reliability layer here ensures Telegram webhooks are acknowledged immediately
    # and ambiguous ChungChi orders can be recovered before the wrapper captures the
    # original bot callbacks.
    try:
        import certificate_reliability  # noqa: F401
    except Exception:
        # Do not prevent the service from booting if a hotfix itself ever fails.
        import traceback
        traceback.print_exc()
