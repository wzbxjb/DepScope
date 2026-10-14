from depscope.ingest.models import Contract


class ExperimentManifest(Contract):
    id: str
    run_id: str
    suite_digest: str
    status: str
    method_results: dict
    usage: dict
    cost: dict
    failures: tuple[dict, ...]
    result_hashes: dict[str, str]
    observed_at: str
