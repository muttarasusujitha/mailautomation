# Level course datasets

One JSON file per technology, each with separate **beginner**, **intermediate** and
**advanced** tracks of 20 days. `categories.json` puts every domain from
`datasets_compact/` into one top-level category.

The TOC generator (`app/level_curriculum.py`) uses these files when a domain has one:

- A request no longer than the level is picked from that level only. The level's capstone is the last day for 5+ day requests.
- A longer request continues into the next level (Beginner → Intermediate → Advanced).
- An Advanced request longer than 20 days starts with the last Intermediate days as a refresher.
- `mixed` takes about a third of the days from each level.
- Domains without a file keep using `datasets_compact/` unchanged. Saved client knowledge (`toc_knowledge`) and custom topics still take priority.

## File format

```json
{
  "domain": "Python",
  "aliases": ["Python Mastery", "Core Python"],
  "certifications": ["..."],
  "tools": ["..."],
  "levels": {
    "beginner": {
      "prerequisites": ["..."],
      "outcomes": ["..."],
      "days": [
        {
          "topic": "Unique day title",
          "subtopics": ["at least 8; 10 if the title has basic/setup/introduction/syntax..."],
          "tools": ["..."],
          "lab_task": "A specific hands-on task",
          "deliverable": "What the participant hands in",
          "checks": [["input or condition", "expected result", "evidence"], ["...", "...", "..."], ["...", "...", "..."]],
          "objectives": ["..."]
        }
      ]
    },
    "intermediate": { "...": "..." },
    "advanced": { "...": "..." }
  }
}
```

Rules checked on load (a file that fails is skipped and its domain keeps the old dataset):

- all three levels exist, each with prerequisites, outcomes and days
- the last day of each level has "Capstone" in its topic
- day topics are unique across all three levels
- every day has 3 checks with different expected results

Check every file and see coverage per category:

```bash
cd microservices/services/trainer-service
PYTHONPATH=.:../.. python -m app.level_curriculum --check
```

All content is marked `unreviewed`. A trainer must confirm technical accuracy,
timings and acceptance cases before client delivery.
