"""Bounded offline project regressions; no actual native/model loading test."""
import sys, unittest
from pathlib import Path
def main():
    repo=Path(sys.argv[1]).resolve()
    tests=repo/"plugins/auto-research-agent/tests"
    sys.path.insert(0,str(tests))
    names=["test_workspace_project_intake","test_workspace_project_host","test_project_stage1","test_project_stage2","test_capability_metric_map","test_research_brief","test_stage1_formal_intake"]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
if __name__=="__main__":
    main()

