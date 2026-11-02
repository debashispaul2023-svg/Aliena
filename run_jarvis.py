#!/usr/bin/env python3
"""Convenience launcher for Jarvis.

Usage (from the directory that contains this file):
    python run_jarvis.py
"""

import os
import sys

# Make the jarvis package importable
root = os.path.dirname(os.path.abspath(__file__))
if root not in sys.path:
    sys.path.insert(0, root)

# Delegate to the real entry point
import runpy
runpy.run_module("jarvis.app.main", run_name="__main__")
