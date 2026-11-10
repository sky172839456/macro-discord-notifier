from pathlib import Path
import unittest
import yaml
from workflow_integrity_check import parse_workflow,check


BASE='''name: Offline fixture
on:
  workflow_dispatch:
jobs:
  example:
    runs-on: ubuntu-latest
    steps:
      - run: echo fixture
        env:
          EXAMPLE_A: "1"
          EXAMPLE_B: "1"
'''


class WorkflowIntegrityTests(unittest.TestCase):
    def test_all_repository_workflows_parse_without_reading_or_running_secrets(self):
        result=check(Path('.github/workflows'))
        self.assertGreaterEqual(result['workflows_parsed'],1)
        self.assertEqual(result['discord_sends'],0)
    def test_on_is_a_trigger_key_and_bad_nested_scalar_indentation_is_rejected(self):
        self.assertIn('on',parse_workflow(BASE))
        with self.assertRaises(yaml.YAMLError):parse_workflow(BASE.replace('          EXAMPLE_B','            EXAMPLE_B'))
    def test_duplicate_env_values_are_not_silently_overwritten(self):
        with self.assertRaises(yaml.YAMLError):parse_workflow(BASE.replace('EXAMPLE_B','EXAMPLE_A'))
    def test_env_arrays_and_steps_with_two_execution_types_are_rejected(self):
        for text in (BASE.replace('EXAMPLE_A: "1"','EXAMPLE_A: [one, two]'),BASE.replace('- run: echo fixture','- uses: actions/checkout@v4\n        run: echo fixture')):
            with self.assertRaises(ValueError):parse_workflow(text)
    def test_missing_trigger_invalid_needs_and_invalid_cron_are_rejected(self):
        for text in (BASE.replace('on:','nothing:'),BASE.replace('runs-on: ubuntu-latest','needs: missing\n    runs-on: ubuntu-latest'),BASE.replace('workflow_dispatch:','schedule:\n    - cron: "invalid"')):
            with self.assertRaises(ValueError):parse_workflow(text)
    def test_python_object_tags_are_not_constructed(self):
        with self.assertRaises(yaml.YAMLError):parse_workflow(BASE.replace('"1"','!!python/object/apply:os.system [echo never-run]',1))
