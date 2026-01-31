"""
Azure Data Factory Client

Simplified ADF operations wrapper using DefaultAzureCredential authentication.
Does not depend on external azure_tools package.
"""

import time
import requests
from typing import List, Dict, Optional

from azure.identity import DefaultAzureCredential
from azure.mgmt.datafactory import DataFactoryManagementClient


class ADFClient:
    """
    Azure Data Factory Client

    Authenticates with DefaultAzureCredential and wraps common ADF operations.
    """

    def __init__(
        self,
        resource_group: str,
        factory_name: str,
        subscription_id: Optional[str] = None,
        credential: Optional[DefaultAzureCredential] = None,
    ):
        """
        Initialize ADF client

        Args:
            resource_group: Azure resource group name
            factory_name: ADF factory name
            subscription_id: Subscription ID (optional, auto-detected)
            credential: Azure credential (optional, auto-creates DefaultAzureCredential)
        """
        self.resource_group = resource_group
        self.factory_name = factory_name
        self.credential = credential or DefaultAzureCredential()

        # Get subscription_id
        if subscription_id:
            self.subscription_id = subscription_id
        else:
            self.subscription_id = self._get_subscription_id()

        # Create DataFactory client
        self.client = DataFactoryManagementClient(
            credential=self.credential,
            subscription_id=self.subscription_id,
        )

        # Cache token
        self._token = None

    # === Pipeline Operations ===

    def list_pipelines(self):
        """
        List all Pipelines

        Returns:
            ItemPaged[PipelineResource], caller should use .as_dict()
        """
        return self.client.pipelines.list_by_factory(
            resource_group_name=self.resource_group,
            factory_name=self.factory_name,
        )

    def get_pipeline(self, name: str) -> Dict:
        """
        Get Pipeline details

        Args:
            name: Pipeline name

        Returns:
            Pipeline definition dictionary
        """
        pipeline = self.client.pipelines.get(
            resource_group_name=self.resource_group,
            factory_name=self.factory_name,
            pipeline_name=name,
        )
        return pipeline.as_dict()

    # === Internal Methods ===

    def _get_subscription_id(self) -> str:
        """Get subscription ID (from environment variable first, then Azure CLI default subscription)"""
        import os
        import subprocess
        import json

        # 1. Read from environment variable first
        sub_id = os.getenv("AZURE_SUBSCRIPTION_ID") or os.getenv("ADF_SUBSCRIPTION_ID")
        if sub_id:
            return sub_id

        # 2. Get default subscription from Azure CLI
        try:
            result = subprocess.run(
                ["az", "account", "show", "--query", "id", "-o", "tsv"],
                capture_output=True,
                text=True,
                check=True,
            )
            sub_id = result.stdout.strip()
            if sub_id:
                return sub_id
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # 3. Fall back to SDK method (for backward compatibility)
        from azure.mgmt.resource import SubscriptionClient

        sub_client = SubscriptionClient(self.credential)
        for sub in sub_client.subscriptions.list():
            return sub.subscription_id
        raise ValueError("No Azure subscription found")

    def _get_token(self) -> str:
        """Get Bearer Token (for REST API calls)"""
        token = self.credential.get_token("https://management.azure.com/.default")
        return token.token

    # === Dataset Operations ===

    def list_datasets(self) -> List[Dict[str, str]]:
        """
        List all Datasets (lightweight summary)

        Returns:
            [{"name": "xxx", "type": "AzureSqlTable", "linked_service": "my_ls"}, ...]
        """
        result = []
        for ds in self.client.datasets.list_by_factory(
            resource_group_name=self.resource_group,
            factory_name=self.factory_name,
        ):
            d = ds.as_dict()
            ls_ref = d.get("properties", {}).get("linked_service_name", {})
            result.append({
                "name": d.get("name", "unknown"),
                "type": d.get("properties", {}).get("type", "unknown"),
                "linked_service": ls_ref.get("reference_name", "unknown"),
            })
        return result

    # === Linked Service Operations ===

    def list_linked_services(self) -> List[Dict[str, str]]:
        """
        List all Linked Services (lightweight summary)

        Returns:
            [{"name": "xxx", "type": "AzureBlobStorage"}, ...]
        """
        result = []
        for s in self.client.linked_services.list_by_factory(
            resource_group_name=self.resource_group,
            factory_name=self.factory_name,
        ):
            d = s.as_dict()
            result.append({
                "name": d.get("name", "unknown"),
                "type": d.get("properties", {}).get("type", "unknown"),
            })
        return result

    def get_linked_service(self, name: str) -> Dict:
        """
        Get Linked Service details

        Args:
            name: Linked Service name

        Returns:
            Linked Service definition dictionary
        """
        # Use REST API to get full details (including typeProperties)
        api_url = (
            f"https://management.azure.com/subscriptions/{self.subscription_id}"
            f"/resourcegroups/{self.resource_group}"
            f"/providers/Microsoft.DataFactory/factories/{self.factory_name}"
            f"/linkedservices/{name}?api-version=2018-06-01"
        )

        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        return response.json()

    def test_linked_service(self, name: str) -> Dict:
        """
        Test Linked Service connection

        Args:
            name: Linked Service name

        Returns:
            Test result dictionary containing succeeded field
        """
        # Get linked service details
        linked_service = self.get_linked_service(name)

        # Build request body
        body = {"linkedService": linked_service}

        # Call test API
        api_url = (
            f"https://management.azure.com/subscriptions/{self.subscription_id}"
            f"/resourcegroups/{self.resource_group}"
            f"/providers/Microsoft.DataFactory/factories/{self.factory_name}"
            f"/testConnectivity?api-version=2018-06-01"
        )

        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

        response = requests.post(api_url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()

    # === Integration Runtime Operations ===

    def list_integration_runtimes(self) -> List[Dict[str, str]]:
        """
        List all Integration Runtimes (lightweight summary)

        Returns:
            [{"name": "xxx", "type": "Managed"}, ...]
        """
        result = []
        for ir in self.client.integration_runtimes.list_by_factory(
            resource_group_name=self.resource_group,
            factory_name=self.factory_name,
        ):
            d = ir.as_dict()
            result.append({
                "name": d.get("name", "unknown"),
                "type": d.get("properties", {}).get("type", "unknown"),
            })
        return result

    def get_integration_runtime_status(self, name: str) -> Dict:
        """
        Get Integration Runtime status

        Args:
            name: Integration Runtime name

        Returns:
            IR status dictionary
        """
        api_url = (
            f"https://management.azure.com/subscriptions/{self.subscription_id}"
            f"/resourcegroups/{self.resource_group}"
            f"/providers/Microsoft.DataFactory/factories/{self.factory_name}"
            f"/integrationruntimes/{name}/getStatus?api-version=2018-06-01"
        )

        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

        response = requests.post(api_url, headers=headers)
        response.raise_for_status()
        return response.json()

    def get_integration_runtime_type(self, name: str) -> str:
        """
        Get Integration Runtime type

        Args:
            name: Integration Runtime name

        Returns:
            IR type (e.g., "Managed", "SelfHosted")
        """
        status = self.get_integration_runtime_status(name)
        ir_type = status.get("properties", {}).get("type")
        if not ir_type:
            raise ValueError(f"Integration Runtime type not found for {name}")
        return ir_type

    def is_interactive_authoring_enabled(self, name: str) -> bool:
        """
        Check if Interactive Authoring is enabled

        Args:
            name: Integration Runtime name

        Returns:
            True if enabled
        """
        status = self.get_integration_runtime_status(name)
        interactive_status = (
            status.get("properties", {})
            .get("typeProperties", {})
            .get("interactiveQuery", {})
            .get("status")
        )
        return interactive_status == "Enabled"

    def enable_interactive_authoring(self, name: str, minutes: int = 10) -> None:
        """
        Enable Interactive Authoring

        Args:
            name: Integration Runtime name
            minutes: Duration (in minutes)

        Raises:
            ValueError: If IR type is not Managed
        """
        # Check IR type
        ir_type = self.get_integration_runtime_type(name)
        if ir_type != "Managed":
            raise ValueError(
                f"Interactive authoring only supported for Managed IR. "
                f"Current type: {ir_type}"
            )

        # Check if already enabled
        if self.is_interactive_authoring_enabled(name):
            return  # Already enabled, no action needed

        # Call enable API
        api_url = (
            f"https://management.azure.com/subscriptions/{self.subscription_id}"
            f"/resourcegroups/{self.resource_group}"
            f"/providers/Microsoft.DataFactory/factories/{self.factory_name}"
            f"/integrationruntimes/{name}/enableInteractiveQuery?api-version=2018-06-01"
        )

        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

        body = {"autoTerminationMinutes": minutes}

        response = requests.post(api_url, headers=headers, json=body)
        response.raise_for_status()

        # Wait for enablement to complete
        max_wait = 180  # Wait up to 3 minutes
        waited = 0
        while waited < max_wait:
            if self.is_interactive_authoring_enabled(name):
                return
            time.sleep(10)
            waited += 10

        raise TimeoutError(
            f"Interactive authoring not enabled after {max_wait} seconds"
        )
