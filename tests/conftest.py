"""Load the integration's HA-independent modules for unit testing.

We import ``const``/``crypto``/``protocol`` under a synthetic ``halo_lite``
package so their relative imports resolve, without pulling in the real
``custom_components.halo_lite.__init__`` (which imports Home Assistant).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "halo_lite"

_pkg = types.ModuleType("halo_lite")
_pkg.__path__ = [str(_ROOT)]
sys.modules.setdefault("halo_lite", _pkg)

for _mod in ("const", "crypto", "protocol"):
    _name = f"halo_lite.{_mod}"
    if _name in sys.modules:
        continue
    _spec = importlib.util.spec_from_file_location(_name, _ROOT / f"{_mod}.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _module
    _spec.loader.exec_module(_module)
