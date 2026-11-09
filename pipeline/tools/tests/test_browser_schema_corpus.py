import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / 'pipeline/fixtures/network-package-v1'
spec = importlib.util.spec_from_file_location('browser_corpus_packager', ROOT / 'pipeline/tools/package_network.py')
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


@pytest.mark.parametrize('case', json.loads((FIXTURE / 'structural-negative-corpus.json').read_text()))
def test_browser_shared_negative_corpus(case):
    value = json.loads((FIXTURE / f"{case['schema']}.json").read_text())
    value[case['field']] = case['value']
    with pytest.raises(ValidationError):
        packager.VALIDATORS[case['schema']].validate(value)
