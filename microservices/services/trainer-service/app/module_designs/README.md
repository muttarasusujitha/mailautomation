Detailed module designs, one file per course (`<course>.json`, matching the file name in
`datasets_levels/` or `datasets_compact/`). Each design is keyed by `level::topic`.

Most designs are model drafts (`"origin": "model_draft_pending_technical_review"`) written by
`python -m app.draft_module_designs`; they need a technical review before client delivery.
The ToC generator reads a course's file only when a ToC uses that course (`app.module_design_store`).
