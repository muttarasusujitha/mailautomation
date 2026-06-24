# LinkedIn Shortlist & AI Pipeline Separation

## ⚠️ CRITICAL ARCHITECTURE RULE

**LinkedIn shortlist MUST NOT merge with AI pipeline shortlist**

The system maintains **3 completely independent trainer systems**:

---

## 1. LinkedIn Shortlist (Manual Leads)
- **Collection**: `trainer_profile_leads`
- **Source**: LinkedIn public profiles, Naukri search
- **Frontend Page**: LinkedInShortlist.jsx
- **API Endpoints**:
  - `GET /api/trainer-profile-leads` - List all LinkedIn leads
  - `PATCH /api/trainer-profile-leads/{lead_id}` - Update lead status
  - `POST /api/trainer-profile-leads/{lead_id}/send-email` - Send email to lead
- **Status Flow**: new → reviewed → contacted → converted/rejected
- **Database**: Completely isolated in `trainer_profile_leads` collection
- **Email Logging**: Logged as `source: "linkedin_shortlist"` in email_logs

---

## 2. AI Pipeline Shortlist (Automated Matching)
- **Collection**: `shortlists` (uses trainers from `trainers` collection)
- **Source**: Database registered trainers + AI pipeline matching
- **Frontend Page**: Shortlist.jsx
- **API Endpoint**:
  - `GET /api/shortlists/{requirement_id}` - Get AI-matched trainers
- **Matching Algorithm**: run_pipeline() in agents/pipeline.py
- **Database**: Uses `trainers` collection + stores results in `shortlists`
- **Email Logging**: Logged as `source: "pipeline"` in email_logs

---

## 3. Database Trainers (Direct Access)
- **Collection**: `trainers`
- **Source**: Directly registered trainers
- **API Endpoint**:
  - `GET /api/trainers` - List all registered trainers
- **Database**: Base trainer profiles with details, status, availability

---

## Separation Rules (DO NOT VIOLATE)

### ❌ NEVER Do This:
1. Add LinkedIn leads (`trainer_profile_leads`) to AI shortlist results
2. Merge LinkedIn leads into `trainers` collection automatically
3. Include LinkedIn leads in `/api/shortlists/` endpoint results
4. Cross-reference leads between `trainer_profile_leads` and `trainers`
5. Automatically promote "converted" LinkedIn leads to trainers

### ✅ DO This Instead:
1. Keep LinkedIn shortlist completely in `trainer_profile_leads` collection
2. Keep AI pipeline using only registered trainers from `trainers` collection
3. Use different email sources in logs: "linkedin_shortlist" vs "pipeline"
4. If LinkedIn lead needs to be a trainer → manually add to `trainers` collection
5. Status flows remain independent:
   - LinkedIn: new → reviewed → contacted → converted/rejected
   - Pipeline: pending_review → approved → confirmed/declined

---

## Code Enforcement Points

### Backend (api.py)
```python
# Line ~10513 - AI Pipeline Shortlist Builder
async def _build_shortlist_for_existing_requirement(db, requirement: dict):
    # ⚠️ ONLY uses: await db["trainers"].find({}, {"_id": 0})
    # NEVER includes trainer_profile_leads
    pass

# Line ~15190 - LinkedIn Shortlist Getter
@router.get("/trainer-profile-leads")
    # ⚠️ ONLY returns from trainer_profile_leads collection
    # NEVER mixes with trainers or shortlists
    pass

# Line ~16206 - LinkedIn Lead Update
@router.patch("/trainer-profile-leads/{lead_id}")
    # Updates ONLY trainer_profile_leads, not trainers
    pass

# Line ~16250 - LinkedIn Email Sender
@router.post("/trainer-profile-leads/{lead_id}/send-email")
    # Logs with source="linkedin_shortlist"
    # Updates trainer_profile_leads status to "contacted"
    # NEVER creates trainer record
    pass
```

### Frontend (React Components)
```jsx
// LinkedInShortlist.jsx
// Renders ONLY trainer_profile_leads
// Uses /trainer-profile-leads endpoints
// Status: new, reviewed, contacted, converted, rejected

// Shortlist.jsx  
// Renders ONLY AI-matched trainers
// Uses /shortlists/{requirement_id} endpoint
// Sources from trainers collection + AI pipeline
```

---

## Database Collections (ISOLATED)

### trainer_profile_leads
- lead_id (unique)
- trainer_name
- contact_email
- domain
- headline
- source (LinkedIn/Naukri)
- status (new/reviewed/contacted/converted/rejected)
- profile_text
- public_resume_url
- created_at, updated_at

**Purpose**: External leads for manual review & outreach

### shortlists
- shortlist_id (unique)
- requirement_id
- top_trainers (array of matched trainers)
- total_matched (count)
- category_filter_applied
- created_at

**Purpose**: AI-generated matches for requirements

### trainers
- trainer_id (unique)
- trainer_name
- email
- domain
- experience_years
- status (available/interested/confirmed/declined)
- match_score
- rank
- created_at, updated_at

**Purpose**: Registered trainer database

---

## When to Violate This Separation

**NEVER** violate this separation without explicit architectural decision.

If LinkedIn lead needs to become a registered trainer:
1. Manually create record in `trainers` collection
2. DO NOT auto-promote based on "converted" status
3. Use `source: "manual_conversion"` or similar in logs
4. Notify admin of manual conversion

---

## Testing Separation

### ✅ Test 1: Verify Collections Are Isolated
```javascript
// Should return different counts
db.trainer_profile_leads.countDocuments() // LinkedIn leads
db.trainers.countDocuments() // Registered trainers
db.shortlists.countDocuments() // AI-generated shortlists
```

### ✅ Test 2: Verify No Cross-References
```javascript
// trainer_profile_leads should NOT have trainer_ids from trainers collection
db.trainer_profile_leads.findOne() // Should NOT have trainer_id field

// trainers should NOT reference lead_id
db.trainers.findOne() // Should NOT have lead_id field
```

### ✅ Test 3: Verify API Separation
```javascript
// /trainer-profile-leads only returns from trainer_profile_leads
GET /api/trainer-profile-leads
// Should NOT include data from trainers collection

// /shortlists only returns from shortlists
GET /api/shortlists/REQ-123
// Should NOT include data from trainer_profile_leads
```

---

## Last Updated
2026-06-23 by GitHub Copilot

**Status**: ✅ SEPARATION ENFORCED
- Documentation added to api.py (lines ~10513, ~15190, ~16206)
- Code comments added to prevent merging
- Architecture validated
