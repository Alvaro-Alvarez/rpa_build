import jira_manager
import ia_manager
import git_manager
import file_manager
import rpa_manager

def start_building():
    # Exporto los issues de jira a la maquina
    issues = jira_manager.get_jira_issues()
    jira_manager.export_issues(issues)

    # Valido que el json exportado sea correcto
    if not ia_manager.valid_json():
        raise ValueError("El json de issues de jira, no estan bien formateados")
    
    # Valido que la rama principal sea la correcta, sino me muevo a ella
    git_manager.process_code_branch()
    
    # Modifico el changeLog
    file_manager.update_change_log()

    #Modifico las versiones de los Assembly
    file_manager.update_assembly_versions()

    # Modifico las versiones de los AIP
    rpa_manager.update_aip_versions()

    
if __name__ == "__main__":
    start_building()
