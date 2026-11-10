"""Offline strict production-mode contract acceptance. No network, sends or state."""
import json
import os
import unittest


def check():
    os.environ['CONTENT_PREFLIGHT_STRICT']='1'
    suite=unittest.defaultTestLoader.discover('tests',pattern='test_content_contract.py')
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    print(json.dumps({'content_preflight_contract':{'strict':True,'tests':result.testsRun,
          'failures':len(result.failures),'errors':len(result.errors),'discord_sends':0,
          'production_state_read':False,'production_state_written':False,
          'scope':'source/copy evidence and final payload; not independent factual or recipient acceptance'}}))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    raise SystemExit(check())
