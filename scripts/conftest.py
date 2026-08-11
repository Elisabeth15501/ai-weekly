"""pytest 根配置：把 scripts/ 加入 sys.path，使 aiweekly 包可被 import。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
