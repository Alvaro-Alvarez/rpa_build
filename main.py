from managers import file_manager, git_manager, ia_manager, jira_manager, rpa_manager


def start_building():
    issues = jira_manager.get_jira_issues()
    jira_manager.export_issues(issues)

    if not ia_manager.valid_json():
        raise ValueError("El json de issues de jira no esta bien formateado.")

    git_manager.process_code_branch()

    file_manager.update_change_log()
    file_manager.update_assembly_versions()

    rpa_manager.update_aip_versions()


def main():
    start_building()


if __name__ == "__main__":
    main()
