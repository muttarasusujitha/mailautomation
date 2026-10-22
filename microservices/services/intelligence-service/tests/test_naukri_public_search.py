import asyncio
from unittest.mock import AsyncMock, patch

from app.clients.naukri_public_search import (
    public_profile_queries,
    public_profile_url,
    search_public_naukri_profiles,
)


def test_public_profile_url_requires_naukri_profile_path():
    assert public_profile_url("https://www.naukri.com/resume/java-developer?ref=search") == (
        "https://www.naukri.com/resume/java-developer"
    )
    assert public_profile_url("http://naukri.com/candidate/123") == "https://naukri.com/candidate/123"
    for value in (
        "https://www.naukri.com/java-jobs",
        "https://www.naukri.com/career-advice/resume-profile",
        "https://www.naukri.com/profile-summary/java",
        "https://www.naukri.com/",
        "https://example.com/profile/java",
        "https://user@www.naukri.com/profile/java",
        "https://www.naukri.com:bad/profile/java",
    ):
        assert public_profile_url(value) == ""


def test_public_profile_queries_use_job_skill_and_location():
    queries = public_profile_queries("Java developer", "Pune")
    assert len(queries) == 4
    assert all("Java developer" in query and "Pune" in query for query in queries)
    assert all("site:naukri.com" in query for query in queries)


def test_search_keeps_only_matching_public_naukri_profiles():
    rows = [
        {"url": "https://www.naukri.com/resume/java-developer", "title": "Java developer", "content": "Java skills"},
        {"url": "https://www.naukri.com/java-jobs", "title": "Java developer jobs", "content": "Java"},
        {"url": "https://www.naukri.com/career-advice/profile-summary", "title": "Java profile", "content": "Java"},
        {"url": "https://example.com/profile/java", "title": "Java developer", "content": "Java"},
        {"url": "https://www.naukri.com/profile/python-developer", "title": "Python developer", "content": "Python"},
    ]
    with patch(
        "app.clients.naukri_public_search.search_public_many",
        new=AsyncMock(return_value=(rows, 4)),
    ) as search:
        profiles = asyncio.run(search_public_naukri_profiles("Java", "Pune", 10))

    assert [profile["source_url"] for profile in profiles] == [
        "https://www.naukri.com/resume/java-developer"
    ]
    search.assert_awaited_once()
    assert search.await_args.args[1:] == (20, ["naukri.com"])


def test_naukri_search_route_uses_public_profiles_without_resdex_flag():
    from app.routes.trainer_profile_leads import SearchPublicRequest, search_public_trainer_leads

    table = AsyncMock()
    table.find_one = AsyncMock(return_value=None)
    table.insert_one = AsyncMock()
    db = {"trainer_profile_leads": table}
    profile = {
        "source_url": "https://www.naukri.com/resume/java-developer",
        "slug": "resume-java-developer",
        "source": "naukri",
        "title": "Java developer",
        "snippet": "Java skills",
    }
    with patch(
        "app.clients.naukri_public_search.search_public_naukri_profiles",
        new=AsyncMock(return_value=[profile]),
    ) as search:
        result = asyncio.run(search_public_trainer_leads(
            SearchPublicRequest(
                source="naukri",
                domains=["Java developer"],
                location="Pune",
                max_results=10,
            ),
            db,
        ))

    assert result["found"] == 1
    assert result["saved_count"] == 1
    saved = table.insert_one.await_args.args[0]
    assert saved["source"] == "naukri"
    assert saved["source_url"] == profile["source_url"]
    search.assert_awaited_once_with("Java developer", "Pune", 10)\n