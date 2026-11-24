# Naukri public job-seeker search prompt

Use this prompt to prepare terms for finding publicly indexed Naukri job-seeker
profiles. It does not search Naukri or reveal private resumes.

```text
Prepare Naukri public profile search terms for this hiring need:

- Role or job title: [role]
- Must-have skills: [skills]
- Nice-to-have skills: [skills, if any]
- Location: [city, region, or country]

Return:

Skills or domains (comma-separated): [1-5 concise phrases]
Location: [one concise location string]
Reasoning: [one short sentence]

Rules:
1. Use only the supplied role, skills, and location. Do not invent candidate
   names, qualifications, experience, or availability.
2. Focus on job seekers for the role. Do not add trainer, instructor, or
   corporate-training terms unless they are part of the job requirement.
3. Keep location separate from the skill phrases. If none is supplied, return
   "Location: [not specified]" rather than guessing.
4. Do not infer or filter candidates by sensitive personal characteristics.
5. Do not claim that profiles were searched, verified, or fetched.
```

The app searches public search indexes with Naukri-only domain filtering and
keeps links that appear to be public profile pages. It does not open profile
pages or access Resdex. Search indexes may return no public profiles; private
candidate resumes require authorized recruiter access to Resdex.
