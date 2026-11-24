from app.toc_generation_agent import generate_toc_from_dataset


def _source(domain):
    toc = generate_toc_from_dataset(domain, 6)
    return (toc.get("agent") or {}).get("source"), toc


def test_bare_oracle_uses_the_rich_database_curriculum_not_a_generic_template():
    source, toc = _source("Oracle")
    assert source == "level_dataset"
    assert "Oracle Database" in (toc.get("title") or "")
    titles = " ".join((day.get("focus_area") or day.get("topic") or "").lower() for day in toc["days"])
    # Specific DBA content, never the "Oracle Foundations / Set up Oracle environment" filler.
    assert "set up oracle environment" not in titles
    assert any(word in titles for word in ("rman", "backup", "performance", "data guard", "rac", "tablespace", "recovery"))


def test_named_oracle_tracks_still_route_to_their_own_datasets():
    assert _source("Oracle Cloud")[1]["title"].startswith("Oracle Cloud")
    assert _source("Oracle Fusion")[1]["title"].startswith("Oracle Fusion")
    assert _source("Oracle Database")[0] == "level_dataset"
