import json
from app.toc_domain_dataset import get_domain
from app.toc_generation_agent import generate_toc_from_dataset
from app.toc_generation_agent import generate_combined_toc_from_datasets


def test_devops_capstone_does_not_add_agentic_ai():
    toc = generate_combined_toc_from_datasets([
        {'technology': 'DevOps', 'days': 3},
        {'technology': 'AWS', 'days': 2},
        {'technology': 'Azure', 'days': 2},
    ])
    final = toc['days'][-1]
    text = json.dumps(final).lower()
    assert 'llmops' not in text
    assert 'langgraph' not in text
    assert 'agent guardrails' not in text
    assert 'acceptance criteria' in text
    assert all('topic' in item for item in final['morning_session']['topics'])


def test_agentic_scope_retains_agent_evaluation():
    toc = generate_combined_toc_from_datasets([
        {'technology': 'Python', 'days': 3},
        {'technology': 'Agentic AI', 'days': 2},
    ])
    assert 'LLMOps' in ' '.join(toc['days'][-1]['subtopics'])


def test_sailpoint_never_resolves_to_data_course():
    assert get_domain('SailPoint IdentityIQ', 3) is None
    toc = generate_toc_from_dataset('SailPoint IdentityIQ', 3)
    assert toc['quality']['status'] == 'requires_regeneration'
