from config import CHANGE_LOG_PATH, JSON_NAME, PREVIOUS_BUILD_VERSION, BUILD_VERSION, GLOBAL_ASSEMBLY_INFO_BACKEND, GLOBAL_ASSEMBLY_INFO_FRONTEND, ASSEMBLY_INFO_API_REST, ASSEMBLY_INFO_EXECUTOR_SER, ASSEMBLY_INFO_ORCHESTRATOR, ASSEMBLY_INFO_TASK_SCHEDULER_SERVICE
import json

def update_change_log():
    with open(JSON_NAME, "r", encoding="utf-8") as f:
        issues_json = json.load(f)

    with open(CHANGE_LOG_PATH, "r", encoding="utf-8-sig") as f:
        change_log_json = json.load(f)

    change_log_json["changelogData"].insert(0, issues_json)

    with open(CHANGE_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(change_log_json, f, indent=2, ensure_ascii=False)

def update_assembly_versions():
    update_assembly(GLOBAL_ASSEMBLY_INFO_BACKEND)
    update_assembly(GLOBAL_ASSEMBLY_INFO_FRONTEND)
    update_assembly(ASSEMBLY_INFO_API_REST)
    update_assembly(ASSEMBLY_INFO_EXECUTOR_SER)
    update_assembly(ASSEMBLY_INFO_ORCHESTRATOR)
    update_assembly(ASSEMBLY_INFO_TASK_SCHEDULER_SERVICE)

def update_assembly(assembly_path):
    with open(assembly_path, "r", encoding="utf-8") as f:
        content = f.read()

    content = content.replace(PREVIOUS_BUILD_VERSION, BUILD_VERSION)

    with open(assembly_path, "w", encoding="utf-8") as f:
        f.write(content)