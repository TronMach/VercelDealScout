# Vercel entry point: every /api/* request is rewritten here (see vercel.json)
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server'))

from server import app  # noqa: E402
