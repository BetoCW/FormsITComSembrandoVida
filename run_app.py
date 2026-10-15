"""Punto de entrada para PyInstaller / doble clic."""
import sys

if len(sys.argv) > 1:
    from autoform.batch import main
else:
    from autoform.gui import main
main()
