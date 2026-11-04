"""Engineering verifier selection and no-I/O boundaries; no actual forbidden calls."""
from contextlib import redirect_stderr
from io import StringIO
import os
import sys
import unittest
from unittest.mock import Mock, patch

import verify_research_v2 as runner


class EngineeringRunnerTests(unittest.TestCase):
    def test_explicit_suite_excludes_simulator_and_database_execution(self):
        self.assertNotIn("test_research_v2", runner.ENGINEERING_SUITES)
        self.assertFalse(any("LabelTests" in n or "test_v2_sqlite_fixtures" in n
                             or "test_v2_fresh_process" in n for n in runner.ENGINEERING_SUITES))
        self.assertIn("test_research_v2.FeatureTests", runner.ENGINEERING_SUITES)
        self.assertIn("test_v2_pipeline_regression", runner.ENGINEERING_SUITES)
        self.assertIn("test_v2_fixed_query_plan", runner.ENGINEERING_SUITES)

    def test_no_report_guard_refuses_writes_reports_network_and_databases(self):
        events=[]
        report=runner.ROOT/"reports/research-v2/V2-ENGINEERING-SYNTHETIC-INVENTED"
        guard=runner.guard_for(report,event_log=events,allow_report_writes=False)
        # Direct audit-callback checks, never actual I/O attempts.
        for event,args in (("open",(str(report/"invented.json"),"w",os.O_WRONLY)),
                           ("open",(str(report/"invented.json"),"r",0)),
                           ("open",(str(runner.ROOT/"invented.py"),None,os.O_CREAT)),
                           ("os.remove",()),("os.mkdir",()),("sqlite3.connect",()),
                           ("socket.connect",()),("subprocess.Popen",())):
            with self.subTest(event=event,args=args),self.assertRaises(RuntimeError):
                guard(event,args)
        self.assertEqual(guard("open",(str(runner.ROOT/"src/demo_futures/research_v2/features.py"),"r",0)),None)

    def test_no_report_requires_explicit_engineering_mode(self):
        with patch.object(sys,"argv",["verify_research_v2.py","--no-report"]), \
             redirect_stderr(StringIO()),self.assertRaises(SystemExit) as raised:
            runner.main()
        self.assertEqual(raised.exception.code,2)

    def test_no_report_loads_only_explicit_names_and_returns_without_receipts(self):
        success=Mock(testsRun=0,failures=[],errors=[],skipped=[])
        success.wasSuccessful.return_value=True
        with patch.object(sys,"argv",["verify_research_v2.py","--engineering-only","--no-report"]), \
             patch.object(sys,"addaudithook") as audit, \
             patch.object(unittest.defaultTestLoader,"loadTestsFromName",return_value=unittest.TestSuite()) as load, \
             patch.object(unittest.TextTestRunner,"run",return_value=success), \
             patch.object(runner,"BLOCKED_EVENTS",[]):
            self.assertEqual(runner.main(),0)
            self.assertEqual([c.args[0] for c in load.call_args_list],list(runner.ENGINEERING_SUITES))
            audit.assert_called_once()

    def test_caught_prohibited_event_or_skip_cannot_pass(self):
        success=Mock(testsRun=1,failures=[],errors=[],skipped=[])
        success.wasSuccessful.return_value=True
        for events,skips in ((["invented-block"],[]),([],[('invented','not executed')])):
            success.skipped=skips
            with patch.object(sys,"argv",["verify_research_v2.py","--engineering-only","--no-report"]), \
                 patch.object(sys,"addaudithook"), \
                 patch.object(unittest.defaultTestLoader,"loadTestsFromName",return_value=unittest.TestSuite()), \
                 patch.object(unittest.TextTestRunner,"run",return_value=success), \
                 patch.object(runner,"BLOCKED_EVENTS",events):
                self.assertEqual(runner.main(),1)


if __name__=="__main__":
    unittest.main()
