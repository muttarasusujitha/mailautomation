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

## Combined programmes (for example Python + AWS + Azure)

`generate_combined_toc_from_datasets` builds one TOC from day allocations:

- Each allocation can set its own level: `{"technology": "Python", "days": 4, "level": "intermediate"}`. Without one, the request level is used.
- A technology with a level file uses it. Hand-written integrated modules (`INTERMEDIATE_COMBINED_TRACKS` / `ADVANCED_COMBINED_TRACKS`) still come first when they fill the allocation; otherwise level-course days come first, followed by those modules.
- A day with a `shared_key` (for example `cloud-concepts` in AWS and Azure) is taught only once, by the first technology.
- `combined.json` holds integration days, such as "Python on AWS" and "AWS and Azure Compared". One is added when both technologies are requested, at the end of the later technology's block, as long as that block keeps at least 2 of its own days.
- The last day is the authored capstone from `combined.json` whose `applies_to` covers every requested technology. When none matches, the generic integrated capstone is used.
- The TOC goes to `requires_review` when a topic repeats under two technologies, or when a beginner topic (setup, basics, fundamentals, introduction...) appears in an intermediate or advanced track.
- Inferred allocations put programming languages before the platforms that use them.
- The TOC flags a gap honestly instead of hiding it. Some older template courses share the same day titles. When one technology runs out of new days because an earlier one already taught them, the TOC shows a review warning. That course needs a level file.

## Finding the technologies in a request (`app/scope_detection.py`)

When a request has no explicit `technology_allocations`, the TOC route reads the client's stated scope (title, technology and topics) against every course name and alias in `datasets_compact` and `datasets_levels`:

- Longest phrase first: "Java Full Stack" is one technology, and "Azure DevOps" is the Azure DevOps product.
- A tool word listed inside another requested course is folded into it. "DevOps; AWS; Azure; Git; Docker" gives three technologies, and "Agentic AI with LangGraph" gives one.
- Broad words ("cloud", "testing", "agile") count only in the stated scope. "Cloud" is dropped when AWS or Azure is named.
- Prerequisites are not topics: "participants already know Python" does not add Python.
- The bare word "SAP" is dropped when a specific SAP course is named: "SAP and S/4HANA" gives SAP S/4HANA, and "SAP BTP CAPM" gives SAP BTP. A module with no level course yet keeps the older SAP course, so "SAP SD and FICO" gives SAP (for SD) plus SAP FICO.
- "Go" is also an everyday word, so on its own it counts only inside a technology list ("Go; Kubernetes", "Python, Go and Docker", "Advanced Go", "Go 5 days"). "Production go-live" and "go to market" do not add Go. "Golang" and "Go programming" always count.
- Notes are read only for the original six programme technologies (DevOps, AWS, Azure, Kubernetes, Python, Agentic AI).
- Days and levels written next to a technology are kept: "Python 5 days, AWS 3 days", "basic Python, advanced AWS". Remaining days are split by weight. A single level word such as "Advanced DevOps with AWS" applies to the whole programme instead.

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
