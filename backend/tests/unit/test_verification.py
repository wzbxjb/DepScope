import json

import pytest

from depscope.analysis.verification import (
    VerificationRecord,
    VerificationRegistry,
    constraints_satisfied,
)
from depscope.identity.coordinates import identify
from depscope.runtime.errors import DomainError
from depscope.sources.records import RecordStore


def test_constraints_require_known_instances_and_matching_versions(snapshot_factory):
    snapshot=snapshot_factory("constraint-test",("root","lib"),(("root","lib"),),root="root")
    components=(snapshot.components[0].model_copy(update={"coordinate":identify("test-app","1.0",None)}),
                snapshot.components[1].model_copy(update={"coordinate":identify("requests","2.32.3",None)}))
    snapshot=snapshot.model_copy(update={"components":components})
    assert not constraints_satisfied(snapshot,[])
    assert constraints_satisfied(snapshot,[{"from_id":"root","to_id":"lib","requirement":"requests>=2.32"}])
    assert not constraints_satisfied(snapshot,[{"from_id":"root","to_id":"lib","requirement":"requests<2.0"}])
    assert not constraints_satisfied(snapshot,[{"from_id":"root","to_id":"lib","requirement":"different-package"}])


def test_registered_signed_report_is_source_checked_and_tampering_rejected(tmp_path):
    store=RecordStore(tmp_path)
    result=store.put(b'constructed verification output',"fixture://verification-output","2026-10-13T00:00:00Z")
    record=VerificationRecord(kind="tests",environment={},source_hashes={"test_output":result.digest},
                              command=("constructed-unit-fixture",),exit_code=0,observed_at=result.observed_at,
                              result_digest=result.digest,producer="depscope.local-backend-v1")
    registry=VerificationRegistry(tmp_path)
    report=tmp_path/"signed.json"
    registry.write_trusted_report((record,),"test-project","test-snapshot",report)
    id=registry.register(report,"test-project","test-snapshot")
    assert registry.lookup(id)["typed_records"] == (record,)
    doc=json.loads(report.read_bytes())
    doc["payload"]["records"][0]["exit_code"]=999
    report.write_text(json.dumps(doc))
    with pytest.raises(DomainError,match="UNTRUSTED_VERIFICATION"):
        registry.register(report,"test-project","test-snapshot")
    store.path_for(result.digest).write_bytes(b'altered output')
    with pytest.raises(DomainError,match="RECORD_INTEGRITY"):
        registry.lookup(id)
