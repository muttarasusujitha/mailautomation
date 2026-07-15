import requests

payload = {
    'toc': {
        'domain': 'DevOps',
        'program_title': 'DevOps Mastery Program',
        'level': 'Intermediate',
        'duration_days': 10,
        'mode': 'Online',
        'trainer_name': 'DevOps Trainer',
        'days': [
            {'day': 1, 'topic': 'DevOps Foundations', 'subtopics': ['CI/CD concepts', 'Infrastructure as Code', 'DevOps toolchain overview', 'Version control with Git', 'Collaboration workflows'], 'tools': ['Git', 'GitHub', 'Docker'], 'jira_focus': 'Set up initial sprint board', 'lab_task': 'Configure Git repo and CI pipeline'},
            {'day': 2, 'topic': 'Linux for DevOps', 'subtopics': ['Linux shell basics', 'File system permissions', 'Process management', 'Networking commands', 'Bash scripting'], 'tools': ['Linux', 'Bash'], 'jira_focus': 'Track server configuration tasks', 'lab_task': 'Deploy a Linux VM and automate health checks'},
            {'day': 3, 'topic': 'Containerization', 'subtopics': ['Docker architecture', 'Container lifecycle', 'Image builds', 'Docker Compose', 'Best practices'], 'tools': ['Docker', 'Docker Compose'], 'jira_focus': 'Create containerization tasks', 'lab_task': 'Build and run a microservice stack in Docker'},
            {'day': 4, 'topic': 'Kubernetes Essentials', 'subtopics': ['K8s architecture', 'Pods and deployments', 'Services and networking', 'ConfigMaps and Secrets', 'Helm basics'], 'tools': ['Kubernetes', 'kubectl', 'Helm'], 'jira_focus': 'Plan cluster deployment work', 'lab_task': 'Deploy an app to a Kubernetes cluster'},
            {'day': 5, 'topic': 'Cloud Infrastructure', 'subtopics': ['AWS basics', 'Azure fundamentals', 'GCP overview', 'VPC and networking', 'Storage services'], 'tools': ['AWS', 'Azure', 'GCP'], 'jira_focus': 'Manage cloud infrastructure tickets', 'lab_task': 'Provision cloud resources using IaC'},
            {'day': 6, 'topic': 'Infrastructure as Code', 'subtopics': ['Terraform core', 'State management', 'Modules', 'Provisioning workflows', 'Policy as code'], 'tools': ['Terraform', 'Pulumi'], 'jira_focus': 'Automate infrastructure changes', 'lab_task': 'Write Terraform for a multi-tier app'},
            {'day': 7, 'topic': 'CI/CD Pipelines', 'subtopics': ['Pipeline design', 'Build automation', 'Testing integration', 'Deployment strategies', 'Rollback plans'], 'tools': ['Jenkins', 'GitHub Actions', 'GitLab CI'], 'jira_focus': 'Automate release pipelines', 'lab_task': 'Build a CI/CD pipeline for code deployment'},
            {'day': 8, 'topic': 'Monitoring & Observability', 'subtopics': ['Logging', 'Metrics', 'Tracing', 'Alerting', 'Dashboarding'], 'tools': ['Prometheus', 'Grafana', 'ELK'], 'jira_focus': 'Create monitoring tasks', 'lab_task': 'Set up observability for a sample app'},
            {'day': 9, 'topic': 'Security & Compliance', 'subtopics': ['Secure CI/CD', 'IAM best practices', 'Secret management', 'Vulnerability scanning', 'Compliance checks'], 'tools': ['Vault', 'SonarQube', 'Snyk'], 'jira_focus': 'Track security remediation', 'lab_task': 'Integrate security scanning into pipeline'},
            {'day': 10, 'topic': 'Release & Support', 'subtopics': ['Release management', 'Incident response', 'Post-mortem practices', 'Continuous improvement', 'Cost optimization'], 'tools': ['Jira', 'Slack', 'PagerDuty'], 'jira_focus': 'Plan release and support handoff', 'lab_task': 'Create an incident response runbook'},
        ],
        'tools_software': ['Git', 'Docker', 'Kubernetes', 'Terraform', 'AWS', 'Azure', 'GCP', 'Jenkins', 'GitHub Actions', 'Prometheus', 'Grafana', 'ELK', 'Vault', 'SonarQube', 'Snyk', 'Linux', 'Bash', 'Helm', 'Pulumi', 'PagerDuty'],
        'certification_roadmap': ['AWS Certified DevOps Engineer', 'Google Professional DevOps Engineer', 'Microsoft Certified: DevOps Engineer Expert', 'Certified Kubernetes Administrator'],
    },
    'to_email': 'sujithaofficial585@gmail.com',
    'trainer_name': 'DevOps Trainer',
    'subject': 'DevOps Mastery Program - 10-Day TOC',
    'body': 'Dear Trainer,\n\nPlease find attached the 10-day DevOps TOC.\n\nRegards,\nTrainerSync Team',
}

response = requests.post('http://127.0.0.1:8004/api/v1/toc/send-email', json=payload, timeout=120)
print(response.status_code)
print(response.text)
