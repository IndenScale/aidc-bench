"""Public vendor-datasheet calibrated multi-view PDK catalog for AIDC AI Factory systems."""

from __future__ import annotations

from pathlib import Path

from texsys.pdk import PdkModule, load_pdk_module

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = PACKAGE_ROOT / "src" / "library" / "modules"


def list_vendor_pdk_modules() -> tuple[str, ...]:
  """Return sorted module slugs available in this vendor PDK package."""
  if not MODULES_ROOT.is_dir():
    return ()
  return tuple(
    sorted(
      entry.name
      for entry in MODULES_ROOT.iterdir()
      if entry.is_dir() and (entry / "module.toml").is_file()
    )
  )


def vendor_pdk_module_dir(slug: str) -> Path:
  """Return the absolute path to a vendor PDK module directory by slug."""
  candidate = (MODULES_ROOT / slug).resolve()
  if not candidate.is_dir() or not (candidate / "module.toml").is_file():
    available = ", ".join(list_vendor_pdk_modules())
    raise FileNotFoundError(f"Unknown vendor PDK module {slug!r}. Available: {available}")
  return candidate


def load_vendor_pdk_module(slug: str) -> PdkModule:
  """Load and validate a multi-view PDK module from this package."""
  return load_pdk_module(vendor_pdk_module_dir(slug))


__all__ = [
  "MODULES_ROOT",
  "PACKAGE_ROOT",
  "list_vendor_pdk_modules",
  "load_vendor_pdk_module",
  "vendor_pdk_module_dir",
]
