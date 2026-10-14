import json

import pytest

from depscope.evaluation.experiments import ExperimentRepository
from depscope.runtime.errors import DomainError


class Ledger:
    def summary(self, id):
        raise DomainError("BUDGET_NOT_FOUND", "No actual run")


def test_unrecorded_files_do_not_appear_as_real_experiments(tmp_path):
    directory = tmp_path / "invented-run"
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "id": "invented-run",
                "run_id": "invented-run",
                "method_results": {"graph_rrf": {"accuracy": 1}},
            }
        )
    )
    assert ExperimentRepository(tmp_path, Ledger()).list().items == ()
    with pytest.raises(DomainError, match="EXPERIMENT_NOT_FOUND"):
        ExperimentRepository(tmp_path, Ledger()).load("../private")
