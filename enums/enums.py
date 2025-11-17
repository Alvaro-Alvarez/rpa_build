from enum import Enum

class Accion(Enum):
    GET_JIRA_ISSUES = "get_jira_issues"
    UPDATE_CHANGE_LOG = "update_change_log"
    UPDATE_ASSEMBLY_VERSIONS = "update_assembly_versions"
    UPDATE_AIP_VERSIONS = "update_aip_versions"
    UPLOAD_CODE_AND_PR = "upload_code_and_pr"
    BUILD_PACKAGE = "build_package"