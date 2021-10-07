"""
This file provides functions for automated migration of Nifi process groups from the DEV to TEST environment.
"""

import os
import logging
import nipyapi
from collections import namedtuple
from nipyapi import versioning
import urllib3
import json
import time

from utils import sanitize_pg

S2P_DEV_ENV_NIFI_URL = "http://localhost:9000/nifi"
S2P_DEV_ENV_NIFI_API_URL = "http://localhost:9000/nifi-api"
S2P_DEV_ENV_NIFI_REG_URL = "http://localhost:18080/nifi-registry"
S2P_DEV_ENV_NIFI_REG_API_URL = "http://localhost:18080/nifi-registry-api"

S2P_TEST_ENV_NIFI_URL = "http://localhost:9001/nifi"
S2P_TEST_ENV_NIFI_API_URL = "http://localhost:9001/nifi-api"
S2P_TEST_ENV_NIFI_REG_URL = "http://localhost:18081/nifi-registry"
S2P_TEST_ENV_NIFI_REG_API_URL = "http://localhost:18081/nifi-registry-api"

# Define the list of Process Groups
PROCESS_GROUPS = ["SampleProcessGroup"]

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def stage_flows_for_export(process_groups):
    """ This function contains the main export logic needed to stage the specified flows. This process checks that
    the Process Groups are committed to version control on the canvas. Additionally, checks are performed to determine
    if uncommitted changes are on the canvas that were not added to version control.

    Args:
        process_groups: an array of process group names to stage

    Returns:
        exported_flows: dictionary of tuples containing each Process Group's name, bucket name, and definition
    """

    exported_flows = {}
    ExportedFlow = namedtuple("ExportedFlow", ["name", "bucket_name", "definition"])

    for pgn in process_groups:
        # Ensure this Process Group exists on the Canvas
        pg = nipyapi.canvas.get_process_group(pgn, greedy=False)

        if pg is None:
            print(F"process group {pgn} was not found on the Nifi Canvas")
            exit(1)

        # Ensure the process group is in the Registry
        if pg.component.version_control_information is None:
            print(F"process group {pgn} is not added to version control")
            exit(1)

        # Ensure there are no uncommitted changes on the Canvas
        diff = nipyapi.nifi.apis.process_groups_api.ProcessGroupsApi().get_local_modifications(pg.id)
        if len(diff.component_differences) > 0:
            print(F"there are uncommitted changes in the process group {pgn}")
            exit(1)

        bucket_id = pg.component.version_control_information.bucket_id
        bucket_name = pg.component.version_control_information.bucket_name
        flow_id = pg.component.version_control_information.flow_id

        # Export the latest version from the Registry
        flow_json = versioning.export_flow_version(bucket_id, flow_id, version=None)
        exported_flows[pgn] = ExportedFlow(pgn, bucket_name, flow_json)

    return exported_flows


def migrate_flows_to_test(exported_flows):
    """ This function verifies parameters, sanitizes process groups, then imports them into the test env.

    Args:
        exported_flows: dictionary of tuples containing each Process Group's name, bucket name, and definition

    Returns:
        None.
    """

    for flow_name, exported_flow in exported_flows.items():
        bucket = versioning.get_registry_bucket(exported_flow.bucket_name)
        if bucket is None:
            bucket = versioning.create_registry_bucket(exported_flow.bucket_name)
            pg = nipyapi.canvas.get_process_group(flow_name, greedy=False)
            if pg is not None:
                print(F"process group exists on Canvas, but not in Registry: {flow_name}")
                exit(1)

        else:
            bflow = versioning.get_flow_in_bucket(bucket.identifier, flow_name)
            pg = nipyapi.canvas.get_process_group(flow_name, greedy=False)
            if bflow is None and pg is not None:
                print(F"process group exists on Canvas, but not in Registry: {flow_name}")
                exit(1)

            if pg is not None:
                diff = nipyapi.nifi.apis.process_groups_api.ProcessGroupsApi().get_local_modifications(pg.id)
                if bflow is not None and pg is not None and len(diff.component_differences) > 0:
                    print(F"there are uncommitted changes in the process group {pg}")
                    exit(1)

    # Get the registry client for the test environment
    reg_clients = versioning.list_registry_clients()
    test_reg_client = None

    # Grab the first registry client we find, assuming we only have one...
    for reg_client in reg_clients.registries:
        test_reg_client = reg_client.component
        break

    # Read the Canvas root element ID to attach Process Groups
    root_pg = nipyapi.canvas.get_root_pg_id()

    for flow_name, exported_flow in exported_flows.items():
        flow = json.loads(exported_flow.definition)

        # Get bucket details
        bucket = versioning.get_registry_bucket(exported_flow.bucket_name)

        # Remove from top level Process Group
        if "parameterContexts" in flow:
            param_ctx = flow["parameterContexts"]
            flow["parameterContexts"] = {}
            if "parameterContextName" in flow["flowContents"]:
                flow["flowContents"].pop("parameterContextName")

        # Sanitize inner Process Groups
        for pg in flow["flowContents"]["processGroups"]:
            sanitize_pg(pg)

        sanitized_flow_def = json.dumps(flow)

        # Check if the process group exists in the bucket
        existing_flow = versioning.get_flow_in_bucket(bucket.identifier, flow_name)

        if existing_flow is None:
            # Import the new flow into the Registry
            vflow = versioning.import_flow_version(
                bucket.identifier,
                encoded_flow=sanitized_flow_def,
                flow_name=flow_name)
            time.sleep(5)

            # Deploy the new flow into the Canvas
            versioning.deploy_flow_version(
                parent_id=root_pg,
                location=(0, 0),
                bucket_id=bucket.identifier,
                flow_id=vflow.flow.identifier,
                reg_client_id=test_reg_client.id,
            )
        else:
            # Update Flow in Registry in place
            vflow = versioning.import_flow_version(
                bucket_id=bucket.identifier,
                encoded_flow=sanitized_flow_def,
                flow_id=existing_flow.identifier)
            time.sleep(5)

            # Check if the Canvas already has the Process Group
            pg = nipyapi.canvas.get_process_group(flow_name, greedy=False)
            if pg is None:
                # Deploy the new flow into the Canvas
                print(root_pg, bucket.identifier, vflow.flow.identifier, test_reg_client.id)
                versioning.deploy_flow_version(
                    parent_id=root_pg,
                    location=(0, 0),
                    bucket_id=bucket.identifier,
                    flow_id=vflow.flow.identifier,
                    reg_client_id=test_reg_client.id,
                )
            else:
                # Update Canvas in place
                versioning.update_flow_ver(process_group=pg)


# --------------------------------------------------------------
# STEP 1. CONNECT TO THE DEV ENV
# --------------------------------------------------------------

print("Connecting to DEV NIFI and REGISTRY instances........")

# Connect to Nifi on DEV
nipyapi.utils.set_endpoint(S2P_DEV_ENV_NIFI_API_URL)
# nipyapi.security.service_login(service="nifi", username="", password="")
connected_nifi_dev = nipyapi.utils.wait_to_complete(
    test_function=nipyapi.utils.is_endpoint_up,
    endpoint_url=S2P_DEV_ENV_NIFI_URL,
    nipyapi_delay=nipyapi.config.long_retry_delay,
    nipyapi_max_wait=nipyapi.config.short_max_wait
)

# Connect to Nifi Registry on DEV
nipyapi.utils.set_endpoint(S2P_DEV_ENV_NIFI_REG_API_URL)
# nipyapi.security.service_login(service="nifi", username="", password="")
connected_reg_dev = nipyapi.utils.wait_to_complete(
    test_function=nipyapi.utils.is_endpoint_up,
    endpoint_url=S2P_DEV_ENV_NIFI_REG_URL,
    nipyapi_delay=nipyapi.config.long_retry_delay,
    nipyapi_max_wait=nipyapi.config.short_max_wait
)

# --------------------------------------------------------------
# STEP 2. DETERMINE WHICH PROCESS GROUPS ON DEV TO MIGRATE
# --------------------------------------------------------------

print("Staging flows for export........")

exported_flows = stage_flows_for_export(PROCESS_GROUPS)

# --------------------------------------------------------------
# STEP 3. CONNECT TO THE TEST ENV
# --------------------------------------------------------------

print("Connecting to TEST NIFI and REGISTRY instances........")

# Connect to Nifi on TEST
nipyapi.utils.set_endpoint(S2P_TEST_ENV_NIFI_API_URL)
# nipyapi.security.service_login(service="nifi", username="", password="")
connected_nifi_test = nipyapi.utils.wait_to_complete(
    test_function=nipyapi.utils.is_endpoint_up,
    endpoint_url=S2P_TEST_ENV_NIFI_URL,
    nipyapi_delay=nipyapi.config.long_retry_delay,
    nipyapi_max_wait=nipyapi.config.short_max_wait
)

# Connect to Nifi Registry on TEST
nipyapi.utils.set_endpoint(S2P_TEST_ENV_NIFI_REG_API_URL)
# nipyapi.security.service_login(service="nifi", username="", password="")
connected_reg_test = nipyapi.utils.wait_to_complete(
    test_function=nipyapi.utils.is_endpoint_up,
    endpoint_url=S2P_TEST_ENV_NIFI_REG_URL,
    nipyapi_delay=nipyapi.config.long_retry_delay,
    nipyapi_max_wait=nipyapi.config.short_max_wait
)

# --------------------------------------------------------------
# STEP 4. VERIFY PARAMETERS, SANITIZE PROCESS GROUPS, & IMPORT
#         THEM INTO THE TEST ENV
# --------------------------------------------------------------

print("Exporting NiFi flows from DEV to TEST........")

migrate_flows_to_test(exported_flows)
