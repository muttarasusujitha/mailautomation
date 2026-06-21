# Budget Workflow Scenario - Complete Example

## Real-World Scenario: Full Stack Training

### Initial Situation
```
CLIENT: ABC Company
REQUIREMENT: Full Stack Training for 5 people
CLIENT BUDGET: INR 20,000
TRAINER FOUND: John (experienced Full Stack trainer)
JOHN'S INITIAL ASKING: INR 30,000
```

---

## Step 1️⃣: Client Provides Budget Information

**Email from Client (ABC Company):**
```
Subject: Full Stack Training Requirement

Hi Clahan Team,

We need Full Stack training for 5 people in our office. 
Our budget for this is INR 20,000.

Please find us a suitable trainer.

Thanks,
ABC Company
```

---

## Step 2️⃣: System Detects Client Budget & Sends mail_budget_confirm

**What System Does:**
- Detects client budget: 20,000
- Searches for suitable trainer: ✅ Found John
- Extracts John's charges from his profile/email

**EMAIL SENT TO CLIENT (ABC Company)**

```
Subject: Training Budget - Full Stack | Confirmation Required

Dear ABC Company,

We have identified a suitable trainer for your Full Stack training.

Budget Details:
Total Training Cost: INR 20,000

This includes the trainer's fees, food, accommodation, and travel charges.

Please confirm if you are comfortable with this budget. If yes, we will proceed with 
the trainer. If not, we will search for another trainer within your budget.

We look forward to your confirmation.

Regards,
Recruitment Team,
Clahan Technologies
```

**Client Response:** ✅ YES, we confirm 20,000 budget

---

## Step 3️⃣: System Calculates Trainer Amount & Sends mail_trainer_budget_negotiate

**Backend Calculation:**
```
Client Budget:        INR 20,000
Clahan Commission:    INR 5,000 (platform fee)
─────────────────────────────────
Trainer Gets:         INR 15,000
```

**EMAIL SENT TO TRAINER (John)**

```
Subject: Training Assignment - Budget Confirmation Required

Dear John,

The client has confirmed their training budget is INR 20,000.

Your charges would be: INR 15,000

This includes food, accommodation, and all travel charges we will provide to you.

Can you proceed with this rate? Please confirm.

Regards,
Clahan Technologies
```

---

## Scenario A: Trainer Accepts ✅

**Trainer's Email Response:**
```
Subject: RE: Training Assignment

Hi,

Yes, I can do this training for INR 15,000. Please proceed.

Thanks,
John
```

**System Action:**
- ✅ Mark trainer as CONFIRMED
- ✅ Move to next phase (interview scheduling)
- ✅ Send mail3 (slot booking)
- ✅ Send mail4 (interview confirmation)
- ✅ Send mail5_ok (trainer selected)

**TRAINING PROCEEDS** ✅

---

## Scenario B: Trainer Asks for More ❌

**Trainer's Email Response:**
```
Subject: RE: Training Assignment

Hi,

I appreciate the opportunity, but I need INR 18,000 (3,000 more) 
because I need additional travel expenses for this location.

Can you accommodate this?

Thanks,
John
```

**System Detects:**
- Trainer asking for: 18,000 (more than offered 15,000)
- Budget mismatch: Extra 3,000 needed
- Decision: REJECT (budget is fixed)

**EMAIL SENT TO TRAINER (John) - mail_trainer_decline**

```
Subject: Training Assignment - Budget Confirmation

Dear John,

Thank you for your response. However, the client's budget is fixed at 
INR 20,000. We cannot accommodate the additional charges you've requested.

Please note that Clahan Technologies provides food, accommodation, and travel 
charges as complete hospitality to trainers.

We will search for another suitable trainer for this opportunity and get back 
to you in case of future requirements where your charges align with the 
client's budget.

Best Regards,
Clahan Technologies
```

**System Action:**
- ❌ Mark trainer as REJECTED
- ❌ Remove from current project
- 🔄 Search for another trainer (back to Step 2)

**TRAINING DELAYED - SEARCH NEW TRAINER** ❌

---

## Budget Workflow Diagram

```
┌──────────────────────────────────────────────────────────────┐
│ 1️⃣ CLIENT: "Our budget is INR 20,000"                        │
└────────────────────────┬─────────────────────────────────────┘
                         │
                    ✅ System Detected
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ 2️⃣ SEND mail_budget_confirm TO CLIENT                        │
│    Question: "Confirm 20,000 budget with all charges?"       │
└────────────────────────┬─────────────────────────────────────┘
                         │
                    ✅ CLIENT CONFIRMS
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ 3️⃣ BACKEND CALCULATION:                                      │
│    Client Budget: 20,000                                     │
│    - Clahan Commission: 5,000                                │
│    = Trainer Gets: 15,000                                    │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ 4️⃣ SEND mail_trainer_budget_negotiate TO TRAINER             │
│    Offer: "15,000 with food, travel, accommodation?"         │
└────────────────┬───────────────────────────────┬─────────────┘
                 │                               │
          ✅ TRAINER YES              ❌ TRAINER ASKS MORE
                 │                               │
                 ▼                               ▼
        PROCEED TO NEXT PHASE      SEND mail_trainer_decline
        (Interview Scheduling)     (Reject & Search New)
        mail3, mail4, mail5_ok    
```

---

## Key Points Summary

| Phase | Email Template | Sent To | Decision |
|-------|---|---|---|
| 1 | Client provides budget | - | 20,000 fixed |
| 2 | mail_budget_confirm | CLIENT | Confirm? |
| 3 | Trainer calculation | - | 15,000 (20k - 5k) |
| 4 | mail_trainer_budget_negotiate | TRAINER | Accept 15k? |
| ✅ YES | Continue workflow | - | Interview scheduling |
| ❌ NO | mail_trainer_decline | TRAINER | Search new trainer |

---

## Important Notes

1. **Budget is Fixed**: Once client confirms, amount cannot increase
2. **Clahan Commission**: Always 5,000 (fixed, not mentioned to client)
3. **Hospitality Included**: Food, accommodation, travel are NOT extra - they're in the trainer's share
4. **No Negotiation**: If trainer asks for more, they are rejected
5. **Platform Benefit**: Trainers get full hospitality while earning their share

---

## Complete 12-Mail Workflow

### Full Journey from Start to Finish

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: INITIAL REQUEST & DETAILS GATHERING                               │
└─────────────────────────────────────────────────────────────────────────────┘

📧 MAIL2: Client Details Request
   Sent To: CLIENT (ABC Company)
   When: Initial requirement received
   Content: "Thank you for sharing Full Stack requirement"
   Asks: Training duration, dates, timings, participants, location, audience level
   Response: Client provides details

   ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: BUDGET CONFIRMATION (3 Mails)                                     │
└─────────────────────────────────────────────────────────────────────────────┘

📧 MAIL_BUDGET_CONFIRM: Client Budget Approval
   Sent To: CLIENT (ABC Company)
   When: Trainer identified, charges known
   Content: "Total Training Cost: INR 20,000"
   Asks: "Please confirm if you are comfortable with this budget?"
   Response: ✅ CLIENT CONFIRMS 20,000

   ↓

📧 MAIL_TRAINER_BUDGET_NEGOTIATE: Trainer Salary Offer
   Sent To: TRAINER (John)
   When: Client budget confirmed
   Content: "Your charges would be: INR 15,000"
   Asks: "Can you proceed with this rate?"
   Response: ✅ TRAINER ACCEPTS 15,000

   ↓

📧 MAIL_TRAINER_DECLINE: Trainer Rejection (if needed)
   Sent To: TRAINER (John) [ONLY if trainer asks for more]
   When: Trainer requests additional charges
   Content: "Client's budget is fixed at INR 20,000"
   Outcome: Search for another trainer
   [NOT SENT in this success scenario]

   ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: INTERVIEW SCHEDULING (2 Mails)                                    │
└─────────────────────────────────────────────────────────────────────────────┘

📧 MAIL3: Interview Slot Booking
   Sent To: TRAINER (John)
   When: Budget confirmed, moving to interview phase
   Content: "Please confirm one of the following slots:"
   Slots: Slot 1, Slot 2, Slot 3
   Response: Trainer confirms preferred slot

   ↓

📧 MAIL4: Interview Schedule Confirmation
   Sent To: TRAINER (John)
   When: Interview slot finalized
   Content: "Your interview has been scheduled"
   Details: Date & Time, Platform, Meeting Link
   Response: Trainer confirms attendance

   ↓

📧 MAIL3_SLOT_FOLLOWUP: Slot Details Request (if needed)
   Sent To: TRAINER (John) [ONLY if slot details incomplete]
   When: Trainer's slot info is vague
   Asks: Exact date, time (AM/PM), 3 available slots
   [NOT SENT in this clear scenario]

   ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: TRAINER SELECTION & CONTENT (3 Mails)                             │
└─────────────────────────────────────────────────────────────────────────────┘

📧 MAIL5_OK: Trainer Selected - Congratulations
   Sent To: TRAINER (John)
   When: Interview completed successfully
   Content: "Congratulations! You have been selected"
   Asks: Share Table of Contents (ToC) and prerequisites
   Response: Trainer sends initial ToC draft

   ↓

📧 MAIL5_NO: Trainer Rejected (if needed)
   Sent To: TRAINER (John) [ONLY if interview didn't go well]
   When: Another trainer is chosen after interview
   Content: "We have decided to proceed with another trainer"
   [NOT SENT in this success scenario]

   ↓

📧 MAIL6_TOC: Table of Contents Request
   Sent To: TRAINER (John)
   When: After selection confirmed
   Asks: 
   - Detailed Table of Contents / Course Agenda
   - Day-wise session breakdown
   - Tools, software, prerequisites required
   - Estimated preparation time
   Response: Trainer sends detailed ToC

   ↓

┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 5: FINAL CONFIRMATION (1 Mail)                                       │
└─────────────────────────────────────────────────────────────────────────────┘

📧 MAIL7_CONFIRM: Final Confirmation Before Training
   Sent To: TRAINER (John)
   When: All details finalized, training about to start
   Content: "Your engagement for Full Stack training confirmed"
   Details:
   - Training Date: June 25, 2026
   - Venue/Platform: Online (Google Meet)
   - Contact details
   Action Items: 
   - Materials ready?
   - Share soft copies 2 days prior
   - Confirm availability 24 hours before
   Response: Trainer confirms readiness

   ↓

✅ TRAINING STARTS - SUCCESS!

```

---

## 12 Mails Reference Table

| # | Mail Name | Recipient | Phase | Purpose | Status |
|---|---|---|---|---|---|
| 1 | **mail2** | CLIENT | Initial | Ask for missing details | ✅ Sent |
| 2 | **mail_budget_confirm** | CLIENT | Budget | Confirm budget (20,000) | ✅ Sent |
| 3 | **mail_trainer_budget_negotiate** | TRAINER | Budget | Offer trainer salary (15,000) | ✅ Sent |
| 4 | **mail_trainer_decline** | TRAINER | Budget | Reject (if asks for more) | ❌ Not sent |
| 5 | **mail3** | TRAINER | Interview | Book interview slots | ✅ Sent |
| 6 | **mail4** | TRAINER | Interview | Confirm interview schedule | ✅ Sent |
| 7 | **mail3_slot_followup** | TRAINER | Interview | Request slot details (if vague) | ❌ Not sent |
| 8 | **mail5_ok** | TRAINER | Selection | Congratulate & ask for ToC | ✅ Sent |
| 9 | **mail5_no** | TRAINER | Selection | Reject trainer (if needed) | ❌ Not sent |
| 10 | **mail6_toc** | TRAINER | Content | Request detailed course agenda | ✅ Sent |
| 11 | **mail2_followup** | TRAINER/CLIENT | Details | Followup reminder (if needed) | ❌ Not sent |
| 12 | **mail7_confirm** | TRAINER | Confirmation | Final confirmation before training | ✅ Sent |

---

## Mails Sent in This Scenario ✅

✅ **mail2** - Initial details request  
✅ **mail_budget_confirm** - Client budget confirmation  
✅ **mail_trainer_budget_negotiate** - Trainer offer (15,000)  
✅ **mail3** - Interview slot booking  
✅ **mail4** - Interview confirmation  
✅ **mail5_ok** - Trainer selected & congratulations  
✅ **mail6_toc** - Course content request  
✅ **mail7_confirm** - Final confirmation  

---

## Mails Not Sent (Conditional) ❌

❌ **mail_trainer_decline** - Only if trainer asks for more money  
❌ **mail3_slot_followup** - Only if slot details are vague  
❌ **mail5_no** - Only if interview fails or trainer rejected  
❌ **mail2_followup** - Only if client doesn't respond to initial request  

---

**Scenario Created:** 2026-06-20  
**System Ready:** All budget templates integrated
