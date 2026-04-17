# Sales Department PPT — Structure Plan

## Design Rules

- **7 slides max**: 15 min total. ~2 min per slide. 5 min saved for core discussion.
- **Keep it simple**: Max 5 lines per slide. Use visuals. Zero tech jargon.
- **Boss perspective first**: Start with value, then safety, then ask them to decide.
- **Invite feedback**: Key slides have discussion prompts. Not a one-way lecture.

---

## PPT Structure (7 slides / 15 min)

### Slide 1: Opening — Set the Stage (1 min)

- **Title**: Let Company Knowledge Empower the Sales Team
- **One-liner**: This platform does 3 things — **auto-collect documents, AI-powered desensitization, rule-based secure sharing**
- **Today's purpose**: We need your help to confirm two things —
  1. What information can be shared? With whom?
  2. How should sensitive information be protected?

---

### Slide 2: How Information Gets Shared — Two Environments, Two Paths (1.5 min)

- **Title**: Two Paths for Information — Private vs Shared
- **Core message**: Our AI platform has two environments. Information takes a different path based on whether it needs to be shared.

- **Left — Private Environment (User Dev Env)**:
  - Information you do NOT need to share → upload to your personal knowledge base
  - Only you can query it through AI
  - Example: PE internal tips, personal work notes
  - **Your data is visible only to you**

- **Right — Shared Environment (Dify Prod Env)**:
  - Information that NEEDS to be shared → enters the shared knowledge base
  - Sharing is controlled by rules:
    - **What type of data** → gets shared with **whom**
    - **Sensitive data** → AI auto-desensitization
  - Desensitized version → searchable by everyone (e.g. CRM business info, Market Search, General Information)
  - Full version with sensitive info → shared only with the owner department and designated recipients

- **Diagram** (side-by-side layout):

```
┌──────────────────┐    ┌────────────────────────────────────┐
│  Private Env      │    │  Shared Env                         │
│                   │    │                                     │
│  Personal KB      │    │  CRM / MOB / COM business info      │
│  PE internal tips │    │  Market Search                      │
│  Open knowledge   │    │  Customer Information                │
│                   │    │  General Information                 │
│  ↓                │    │  Rule Agents (HR/GA/BE/SCM/BPM)     │
│  Only YOU can     │    │                                     │
│  query this       │    │  ↓                    ↓             │
│                   │    │  Desensitized ver →   Full ver →    │
│                   │    │  everyone             owner dept +  │
│                   │    │                       designated    │
│                   │    │                       recipients    │
└──────────────────┘    └────────────────────────────────────┘
```

- **One-line summary**: Don't need to share → put it in the private environment, use it yourself. Need to share → it enters the shared environment, securely shared by rules.

---

### Slide 3: Full Pipeline — From Collection to Access (3 min)

- **Title**: Auto-collect → AI Processes by Rules → Different People See Different Content
- **4-step flow** (left to right):

```
① Auto-collect         ② AI processes by rules    ③ Distribute by rules           ④ User access
SharePoint             Identify sensitive content  Full ver → owner dept           Owner dept → full ver
Email                  Generate desensitized ver            + designated recipients Designated → full ver
CRM / OPP              Generate full ver           Desensitized ver → everyone     Everyone else → desens. ver
```

- **Step ① Auto-collect**:
  - System auto-fetches documents from SharePoint / email / CRM
  - No manual upload needed. Just place documents in the folder.

- **Step ② AI processes by rules**:
  - AI follows pre-set department rules to identify sensitive content in documents
  - Generates two versions: **full version** (contains sensitive info) + **desensitized version** (sensitive info removed)

- **Step ③ Distribute by rules**:
  - **Full version** → visible to everyone in the owner department + designated recipients
  - **Desensitized version** → visible to everyone

- **Step ④ Who sees what?** (access matrix):

  | Version | Owner department | Designated recipients | Everyone else |
  |---------|-----------------|----------------------|---------------|
  | Full version (with sensitive info) | Can see | Can see | Cannot see |
  | Desensitized version (sensitive info removed) | Can see | Can see | Can see |

- **Key guarantees**: The owner department decides who the "designated recipients" are / AI suggests, humans make the final call / Rules can be pre-set by document type
- **Discussion prompt**: Where do you currently store your sales documents?

---

### Slide 4: Benefits for the Sales Department (1 min)

- **Title**: What's in it for you? Won't add to your workload.
- **Benefits** (big text, one per line):
  - Winning deal plans become AI knowledge — new hires get up to speed fast
  - PE/R&D see your requirement docs — they provide more accurate solutions
  - AI answers product/customer questions 24/7 — less repetitive work
  - Save roughly 80% of data preparation time
- **About workload**:
  - System auto-collects. No manual upload needed.
  - Once rules are set, they run automatically. No doc-by-doc approval.
  - Department admins can adjust sharing rules anytime.
- **Discussion prompt**: Which of these scenarios is most valuable to your team?

---

### Slide 5: AI Desensitization — A Real Example (1 min)

- **Title**: What does AI desensitization look like?
- **Original vs Desensitized version** (side-by-side comparison):

  | Original (owner dept + designated recipients only) | Desensitized version (visible to everyone) |
  |---------------------------------------------------|-------------------------------------------|
  | Basic tier pricing: ¥9,999 | Products come in Basic and Premium tiers |
  | Premium tier pricing: ¥19,999 | (Detailed pricing is confidential — contact Sales) |
  | Key account discount: up to 30% off | Key account discount policy available |

- **3 desensitization strategies**:
  - **Remove**: Delete the entire section (e.g. remove the "Staff Changes" chapter)
  - **Replace**: Substitute with a placeholder (e.g. "Pricing: [confidential]")
  - **Summarize**: AI rewrites into a vague description (like the example above)
- **Human fallback**: Desensitization results can be manually reviewed. If AI gets it wrong, a human corrects it.

---

### Slide 6: We Need You to Confirm the Rules — Core Discussion (5 min)

- **Title**: Help Us Define the Rules
- **4 specific questions** (each with options — let the bosses pick or discuss):

  **Q1: Visibility within your department**
  - A. Everyone in Sales can see all Sales documents by default
  - B. Need to specify by team or role

  **Q2: Which documents can be shared with PE/R&D?**
  - A. Product requirement docs — share?
  - B. OPP (deal) plans — share?
  - C. Customer cases — share?
  - D. Pricing / discounts — absolutely not shared?

  **Q3: Sharing method**
  - A. Share the full version (PE needs all the details to build solutions)
  - B. Share the desensitized version only (hide sensitive data)

  **Q4: Approval process**
  - A. Rules execute automatically; admin spot-checks periodically
  - B. Every document requires manual admin review before sharing

- **Preparation**: If a rules configuration UI screenshot is available, show it here — "Setting rules is this simple"

---

### Slide 7: Questions to Confirm & Support We Need (2 min)

- **Title**: We Need Your Confirmation and Support
- **Part 1: Questions to Confirm**
  - **Q1**: Do you have any concerns about the content we are sharing right now?
  - **Q2**: Do you have any questions about the access control rules we've designed? What kind of data counts as sensitive to you? Demand info? Pricing? ...
- **Part 2: Support We Need**
  - Once the system is ready, we will present this platform to each department. We ask for your support.
  - We also hope you can share within your department: what kind of information should be shared on this platform.
- **Closing line**: This is not a technology project. It's a project to turn sales experience into a company asset.

---

## Production Tips

### Visual Design

- Use company brand colors. Clean, professional style.
- Slide 3 is the core slide — use a flow diagram + access matrix table, fill the entire page.
- Slide 5: side-by-side layout for original vs desensitized. Make the contrast obvious.
- Slide 6: large font, card-style options layout. Easy to point at during live discussion.

### Pacing

- **Slide 1** (1 min): One line explaining the 3 core functions
- **Slide 2** (1.5 min): Private vs Shared
- **Slide 3** (3 min): Core slide — collect → desensitize → distribute → access + access matrix
- **Slide 4** (1 min): Make the bosses think "this matters to my team"
- **Slide 5** (1 min): Real example showing AI desensitization in action
- **Slide 6** (5 min): This is the real purpose of the meeting. Walk through Q1–Q4. Write down their answers.
- **Slide 7** (2 min): Confirm questions + ask for support

### Speaker Tips

- On Slide 3, **focus on the Step ④ access matrix** — let bosses see "who sees what" at a glance
- On Slide 5, **use the real example** — let them feel the AI is capable
- On Slide 6, **don't rush through it**. One question at a time. Record their answers.
- **Absolutely avoid** mentioning tech terms: Dify, RAG, FastAPI, metadata, knowledge base chunking
