"""Send the approved 5-day Advanced DevOps TOC as an Excel attachment."""
import base64
import os
import sys
from pathlib import Path

import requests

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "services" / "document-service"))

from app.routes.excel import _toc_to_excel


def env_value(name: str) -> str:
    for line in (root / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip()
    return value if "value" in locals() else ""


toc = {
    "title": "Advanced DevOps Training Programme",
    "domain": "DevOps",
    "duration_days": 5,
    "level": "Advanced",
    "mode": "Online",
    "generation_mode": "template",
    "overview": "Advanced hands-on DevOps programme covering platform engineering, secure delivery, cloud-native operations, observability, and reliability.",
    "days": [
        {"day": 1, "title": "Platform Engineering and GitOps", "subtopics": ["Internal developer platforms and golden paths", "GitOps operating model with Argo CD", "Multi-environment configuration and promotion", "Terraform modules, remote state and policy as code"], "tools": "Backstage, GitHub, Terraform, Argo CD, Kubernetes", "lab": "Create a golden path that provisions a service repository, infrastructure baseline and GitOps deployment.", "learning_objectives": ["Design governed self-service delivery paths", "Implement GitOps controls"]},
        {"day": 2, "title": "Enterprise CI/CD and Release Engineering", "subtopics": ["Pipeline architecture and reusable workflows", "Ephemeral environments and artifact promotion", "Feature flags, approvals and release governance", "Rollback and disaster-recovery design"], "tools": "GitHub Actions, Jenkins, Nexus, Argo CD", "lab": "Build a multi-stage pipeline with signed artifacts, approval gates and automated rollback.", "learning_objectives": ["Engineer traceable release pipelines", "Implement safe rollback"]},
        {"day": 3, "title": "DevSecOps and Software Supply Chain Security", "subtopics": ["SBOMs, provenance and artifact signing", "SAST, DAST, container and IaC scanning", "Secrets management and workload identity", "Kubernetes admission control and policy enforcement"], "tools": "Trivy, Syft, Cosign, Vault, Kyverno", "lab": "Enforce signed images, vulnerability thresholds and admission policies for a Kubernetes release.", "learning_objectives": ["Secure the software supply chain", "Apply runtime policy controls"]},
        {"day": 4, "title": "Observability, SRE and Progressive Delivery", "subtopics": ["SLIs, SLOs and error budgets", "Metrics, logs and distributed tracing", "Canary and blue-green delivery", "Incident response, runbooks and chaos testing"], "tools": "Prometheus, Grafana, Loki, Tempo, Argo Rollouts", "lab": "Run a metrics-driven canary deployment that automatically rolls back after an SLO breach.", "learning_objectives": ["Operate with SLO evidence", "Automate progressive delivery"]},
        {"day": 5, "title": "Cloud-Native DevOps Capstone", "subtopics": ["Multi-cluster and multi-region architecture", "FinOps and capacity optimisation", "Resilience, security and compliance review", "Operational handover and technical decision records"], "tools": "Kubernetes, Terraform, Argo CD, Prometheus, Grafana", "lab": "Deliver and defend an end-to-end secure GitOps platform with observability, progressive delivery and an operations runbook.", "learning_objectives": ["Integrate advanced DevOps practices", "Produce an operational handover"]},
    ],
}

workbook = _toc_to_excel(toc)
fallback_user = env_value("GMAIL_FALLBACK_USER")
fallback_password = env_value("GMAIL_FALLBACK_APP_PASSWORD")
payload = {
    "to": "sujithaofficial585@gmail.com",
    "subject": "Advanced DevOps Training Programme - 5-Day TOC",
    "body": "Dear Sujitha,\n\nPlease find attached the Table of Contents for the 5-day Advanced DevOps training programme.\n\nRegards,\nClahan Technologies",
    "attachments": [{"filename": "advanced_devops_5_day_toc.xlsx", "content_base64": base64.b64encode(workbook).decode(), "subtype": "vnd.openxmlformats-officedocument.spreadsheetml.sheet"}],
    "smtp_config": {"smtpUser": fallback_user, "smtpPass": fallback_password, "fromEmail": fallback_user, "fromName": "Clahan Technologies"},
}
response = requests.post("http://127.0.0.1:8002/api/v1/email/send", json=payload, timeout=60)
response.raise_for_status()
print(response.text)
