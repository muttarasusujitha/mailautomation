from app.routes.shortlists import (
    _client_training_summary,
    _explicit_lab_workbook_required,
    _requested_client_attachments,
    _requested_toc_output_format,
    _trainer_scope_attachments,
)


def test_excel_reference_keeps_toc_in_excel_format():
    requirement = {
        "requested_details": ["ToC"],
        "attachment_names": ["Client Training Agenda.xlsx"],
    }
    assert _requested_client_attachments(requirement) == (False, True, False)
    assert _requested_toc_output_format(requirement) == "xlsx"


def test_word_reference_uses_detailed_client_ready_format():
    requirement = {
        "requested_details": ["Course agenda"],
        "source_attachments": [{"filename": "Five Day Course TOC.docx"}],
    }
    assert _requested_toc_output_format(requirement) == "pdf"


def test_toc_without_format_defaults_to_editable_excel():
    requirement = {"requested_details": ["Table of Contents"]}
    assert _requested_toc_output_format(requirement) == "xlsx"


def test_lab_cost_is_detected_separately_from_toc_and_profile():
    requirement = {
        "requested_details": ["Trainer Profile", "ToC", "Lab Cost"],
    }
    assert _requested_client_attachments(requirement) == (True, True, True)


def test_client_profile_linkedin_id_toc_and_lab_workbook_request_is_detected():
    requirement = {
        "client_requirement_text": "Please share the client profile and LinkedIn ID, ToC, and lab workbook.",
    }
    assert _requested_client_attachments(requirement) == (True, True, True)
    assert _explicit_lab_workbook_required(requirement) is True


def test_lab_setup_is_not_misclassified_as_explicit_lab_workbook_request():
    requirement = {"client_requirement_text": "Please arrange local lab setup and access."}
    assert _requested_client_attachments(requirement) == (False, False, True)
    assert _explicit_lab_workbook_required(requirement) is False


def test_safe_client_excel_scope_is_forwarded_to_trainer_mail1():
    requirement = {
        "source_attachments": [{
            "filename": "Azure DATA.xlsx",
            "content_base64": "YWJj",
            "size_bytes": 3,
            "safe_client_scope": True,
        }],
    }
    assert _trainer_scope_attachments(requirement) == [{
        "filename": "Azure DATA.xlsx",
        "content_base64": "YWJj",
        "subtype": "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }]


def test_unsafe_or_uncaptured_attachment_is_not_forwarded():
    requirement = {
        "source_attachments": [{
            "filename": "unknown.exe",
            "content_base64": "YWJj",
            "size_bytes": 3,
            "safe_client_scope": False,
        }],
    }
    assert _trainer_scope_attachments(requirement) == []


def test_client_training_summary_includes_dates_duration_and_timings():
    requirement = {
        "technology": "DevOps",
        "training_dates": "2026-09-08 to 2026-09-20",
        "duration": "12.0 days",
        "timings": "9:00AM to 5:00pm",
    }

    assert _client_training_summary(requirement) == "\n".join([
        "- Technology: DevOps",
        "- Training dates: 2026-09-08 to 2026-09-20",
        "- Duration: 12.0 days",
        "- Timings: 9:00AM to 5:00pm",
    ])
