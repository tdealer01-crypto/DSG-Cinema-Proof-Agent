from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from deploy_z3_azure_rest import AzureDeployer


def test_deployment_reuses_solver_secret_in_container_and_output(tmp_path):
    deployer = AzureDeployer("subscription", "tenant", verbose=False)
    deployer.access_token = "access-token"
    deployer.solver_secret = "s" * 64
    deployer.registry_password = "registry-password"
    response = Mock(status_code=201)
    response.json.return_value = {}

    with patch("deploy_z3_azure_rest.requests.put", return_value=response) as put:
        container_url = deployer.create_container_instance()

    body = put.call_args.kwargs["json"]
    variables = body["properties"]["containers"][0]["properties"]["environmentVariables"]
    deployed_secret = next(
        item["secureValue"]
        for item in variables
        if item["name"] == "DSG_SOLVER_SHARED_SECRET"
    )

    output = tmp_path / "deployment.txt"
    deployer.output_path = output
    deployer.save_outputs(container_url)

    assert deployed_secret == deployer.solver_secret
    assert body["properties"]["imageRegistryCredentials"][0]["password"] == "registry-password"
    assert deployer.solver_secret in output.read_text(encoding="utf-8")
    assert output.stat().st_mode & 0o777 == 0o600


def test_container_creation_fails_closed_on_azure_error():
    deployer = AzureDeployer("subscription", "tenant", verbose=False)
    deployer.access_token = "access-token"
    deployer.registry_password = "registry-password"
    response = Mock(status_code=403, text="forbidden")

    with patch("deploy_z3_azure_rest.requests.put", return_value=response):
        with pytest.raises(RuntimeError, match="HTTP 403"):
            deployer.create_container_instance()


def test_health_check_fails_closed_on_transport_error():
    deployer = AzureDeployer("subscription", "tenant", verbose=False)

    with patch(
        "deploy_z3_azure_rest.requests.get",
        side_effect=requests.ConnectionError("offline"),
    ):
        with pytest.raises(RuntimeError, match="health check"):
            deployer.test_health("https://z3.example.test")
