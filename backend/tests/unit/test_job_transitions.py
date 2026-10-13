import pytest

from depscope.jobs.models import can_transition


@pytest.mark.parametrize('source,target,allowed',[
    ('queued','validating',True),('queued','ready',False),('validating','writing',True),
    ('fetching','cancelled',True),('writing','ready',True),('ready','cancelled',False),
    ('failed','queued',False),('interrupted','queued',True),('cancelled','writing',False),
])
def test_explicit_job_state_machine(source,target,allowed):
    assert can_transition(source,target) is allowed
