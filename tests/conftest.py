"""Damit `from lib import ...` auch ohne installiertes Paket funktioniert."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
