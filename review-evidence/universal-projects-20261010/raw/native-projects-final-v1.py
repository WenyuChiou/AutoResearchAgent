import sys
import unittest
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path.cwd() / "plugins/auto-research-agent/tests"))
    names = ["test_workspace_project_model", "test_project_model_factory", "test_project_workspace_launcher", "test_capability_metric_map"]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
