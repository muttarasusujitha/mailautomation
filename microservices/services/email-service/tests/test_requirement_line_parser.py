from app.routes.inbox import _extract_requirement_from_email


def test_requirement_parser_preserves_bullets_and_regular_sentences():
    body = """Dear Clahan,
We are pleased to confirm the 20-day Advanced DevOps offline training program.
- Dates: 10 September 2026 to 7 October 2026
- Mode: Offline / classroom
- Participants: 20
- Commercial: INR 180,000
- Taxes: Inclusive / Exclusive of GST
The program will cover Linux, Git, Docker, Kubernetes, CI/CD, Jenkins, cloud deployment, monitoring, security, and a practical capstone project.
To finalize the batch, please share or confirm:
- Approved Table of Contents (ToC)
- Lab requirements and required tools 20 days
- Local or cloud lab preference 3 hour per day
- Trainer CV approval
Once we receive the ToC and lab requirements, we will finalize the curriculum, lab setup, and trainer allocation.
Regards,
Client
"""

    extracted = _extract_requirement_from_email(
        "DevOps Training Requirement", body, "client@example.com", "Client"
    )

    categories = [item["category"] for item in extracted["requirement_items"]]
    assert {"batch_confirmation", "training_schedule", "commercials", "taxes", "training_scope"}.issubset(categories)
    assert {"toc", "lab_requirements", "lab_delivery_preference", "trainer_profile", "workflow_condition"}.issubset(categories)
    assert extracted["lab_cost_requested"] is True
    assert extracted["lab_hours_per_day"] == 3.0
    assert extracted["trainer_cv_approval_requested"] is True
    assert "practical capstone project" in extracted["requirement_source_text"].lower()
