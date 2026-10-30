import os
import sys

# Tests import modules the same way server.py does: `from src...`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
