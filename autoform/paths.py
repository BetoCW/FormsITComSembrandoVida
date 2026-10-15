"""Rutas del proyecto (funciona tambien empaquetado con PyInstaller)."""
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent.parent

CONFIG = ROOT / "config"
DATA = ROOT / "data"
FORM_CACHE = DATA / "form_cache"
PROFILE = DATA / "browser_profile"
OUTPUT = ROOT / "output"
