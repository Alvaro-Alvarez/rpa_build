import json
import requests
import pandas as pd
from datetime import datetime
from requests.auth import HTTPBasicAuth
from config import JIRA_URL, JIRA_TOKEN, JIRA_JQL, JIRA_USER, BUILD_VERSION, XLXS_NAME, JSON_NAME

def get_jira_issues():
    jira_jql = JIRA_JQL.replace('{BUILD_VERSION}', BUILD_VERSION)
    url = f"{JIRA_URL}/rest/api/3/search/jql"
    auth = HTTPBasicAuth(JIRA_USER, JIRA_TOKEN)    
    headers = {
        "Accept": "application/json"
    }
    
    query = {
        'jql': jira_jql,
        'maxResults': 100,
        'fields': 'key,summary'
    }

    response = requests.request(
        "GET",
        url,
        headers=headers,
        params=query,
        auth=auth
    )

    if response.status_code != 200:
        print(f"Error: {response.status_code} - {response.text}")
        return None
    
    data = response.json()

    issues_dict = {
        issue['key']: issue['fields']['summary'] 
        for issue in data.get('issues', [])
    }
    
    return issues_dict

def export_issues(issues):
    # 1. Exportar a Excel
    df = pd.DataFrame(list(issues.items()), columns=['Key', 'Summary'])
    df.to_excel(XLXS_NAME, index=False)
    
    # 2. Exportar a JSON
    issues_dict_cleaned = {
        key: value.replace('"', "'") 
        for key, value in issues.items()
    }

    json_output = {
        "versionNumber": BUILD_VERSION,
        "versionDate": datetime.now().strftime("%d/%m/%Y"),
        "changeLogDetails": [f"{key} - {value}" for key, value in issues_dict_cleaned.items()]
    }
    
    with open(JSON_NAME, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)