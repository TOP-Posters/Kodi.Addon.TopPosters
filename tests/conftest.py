import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "service.topposters"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
