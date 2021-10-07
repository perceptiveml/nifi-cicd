"""
This file provides utility functions for migrating Nifi process groups from the DEV to TEST environment.
"""


def sanitize_pg(pg_def):
    """ This function sanitizes the processGroup section from parameterContext references and does a
      recursive cleanup of the processGroups if multiple levels are found.

    Args:
        pg_def: processGroup section from parameterContext references

    Returns:
        pg_def: sanitized processGroup section
    """

    if "parameterContextName" in pg_def:
        pg_def.pop("parameterContextName")

    if "processGroups" not in pg_def or len(pg_def["processGroups"]) == 0:
        return pg_def

    for pg in pg_def["processGroups"]:
        sanitize_pg(pg)
