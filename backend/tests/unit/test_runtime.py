import pytest
from fastapi.testclient import TestClient

from depscope.runtime.app import create_app
from depscope.runtime.config import Settings
from depscope.runtime.errors import DomainError


def test_live_service_never_exposes_api_key():
    settings = Settings.from_env({"DEEPSEEK_API_KEY": "sentinel-secret"})
    client = TestClient(create_app(settings))
    assert client.get("/health/live").json() == {"status": "alive"}
    assert "sentinel-secret" not in repr(settings)
    assert "sentinel-secret" not in str(settings.public_summary())


def test_missing_services_are_explicit_and_import_is_connection_free():
    settings = Settings.from_env({})
    assert settings.public_summary()["generation_configured"] is False
    assert settings.public_summary()["database_configured"] is False
    assert TestClient(create_app(settings)).get("/health/live").status_code == 200


@pytest.mark.parametrize("env, pointer", [
    ({"DEEPSEEK_BASE_URL": "file:///private"}, "/DEEPSEEK_BASE_URL"),
    ({"DEEPSEEK_BASE_URL": "https://user:password@example.com"}, "/DEEPSEEK_BASE_URL"),
    ({"NEO4J_URI": "invalid"}, "/NEO4J_URI"),
    ({"AI_MAX_CALLS": "-1"}, "/AI_MAX_CALLS"),
    ({"AI_MAX_AMOUNT_USD": "-0.01"}, "/AI_MAX_AMOUNT_USD"),
    ({"AI_MAX_AMOUNT_USD": "NaN"}, "/AI_MAX_AMOUNT_USD"),
])
def test_invalid_configuration_reports_field(env, pointer):
    with pytest.raises(DomainError) as exc:
        Settings.from_env(env)
    assert exc.value.code == "CONFIG_INVALID"
    assert exc.value.pointers == (pointer,)


def test_error_contract_preserves_safe_field_locations():
    error = DomainError("INVALID_BOM", "Invalid dependency reference", ("/dependencies/0/ref",))
    assert error.code == "INVALID_BOM"
    assert error.retryable is False
    assert error.as_dict() == {
        "code": "INVALID_BOM", "message": "Invalid dependency reference",
        "pointers": ["/dependencies/0/ref"], "retryable": False,
    }


async def test_doctor_never_calls_paid_generation(respx_mock):
    from depscope.runtime.doctor import doctor
    settings = Settings.from_env({"DEEPSEEK_API_KEY": "sentinel-secret"})
    result = await doctor(settings)
    assert result["generation"] == {"status": "configured", "tested": False}
    assert result["database"]["status"] == "not_configured"
    assert len(respx_mock.calls) == 0
