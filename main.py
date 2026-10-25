import importlib.util
import sys

if sys.version_info < (3, 9):
    sys.exit("GW2 Achievement Helper needs Python 3.9 or newer.")

if importlib.util.find_spec("PySide6") is None:
    sys.exit("PySide6 is missing. Run:  python -m pip install -r requirements.txt  (or just use run.bat)")

from gw2ach.ui.app import main

if __name__ == "__main__":
    main()
