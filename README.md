# GEIZMO

**Guided Enhanced Intelligent Zone for Marking and Overview**

An AI-powered web revision platform built at the University of Botswana. Students submit practice answers to past exam questions and receive detailed, personalised feedback in about two seconds. Lecturers get a system that adapts to their own marking style over time, without needing pre-labelled training data.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [How the AI Grading Works](#how-the-ai-grading-works)
- [Active Learning Pipeline](#active-learning-pipeline)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Database Setup](#database-setup)
- [Running the App](#running-the-app)
- [User Roles](#user-roles)
- [Known Limitations](#known-limitations)
- [Roadmap](#roadmap)
- [Author](#author)

---

## Overview

Students often have no reliable way to check open-ended answers while revising, and lecturers cannot give every student individual feedback at scale. GEIZMO closes that gap. A student picks a past paper question, writes or uploads an answer, and gets back a predicted mark, highlighted errors, feedback that quotes their own words, and recommended study resources.

Design principles:

- **Private by design.** All AI processing runs locally. No student data is sent to an external service.
- **Grounded, not generative.** GEIZMO uses Sentence-BERT rather than a generative LLM, so feedback is tied to the marking criteria the lecturer defined and cannot hallucinate a wrong answer into a correct one.
- **Adapts to the lecturer.** High-quality student answers are flagged for lecturer review, and approved answers are used to retrain the mark calibration model.
- **Degrades gracefully.** If an AI library is unavailable the system keeps working with reduced accuracy instead of failing.

---

## Key Features

- Three role-based dashboards (student, lecturer, admin) plus a public landing page with live statistics
- Registration with a 6-digit OTP sent by email
- Past papers, model answers and key points managed by lecturers
- Answers submitted as typed text or uploaded as PDF or DOCX files
- Seven-stage AI grading pipeline (see below)
- Phrase-level error detection that catches wrong substitutions even when overall similarity is high
- Feedback that quotes the student's actual phrases in both strengths and errors
- Learning resource recommendations from textbooks and study materials
- Active learning pipeline with lecturer review and one-click retraining
- AI accuracy dashboard for lecturers (MAE, Pearson r, grade band accuracy, key-point F1) with plain-English explanations
- Maintenance mode controlled by the admin
- Dark mode across all interfaces
- REST API with 70+ routes

---

## How the AI Grading Works

Each submission passes through these stages:

1. **Text preprocessing:** cleans and normalises the answer
2. **Semantic similarity:** Sentence-BERT (`all-MiniLM-L6-v2`) compares the answer to the lecturer's model answers by meaning, not just keywords
3. **Key-point detection:** checks which of the lecturer's key points the answer covers
4. **Phrase-level error analysis:** flags semantically wrong substitutions (for example, "cows" where "computers" was expected) and applies a penalty
5. **Mark prediction:** a score based on key-point coverage and similarity, calibrated by Ridge regression once enough approved exemplars exist
6. **Feedback generation:** strengths and errors, referencing the student's own wording
7. **Resource recommendation:** points the student to relevant study material

**Fallback chain:** Sentence-BERT, then TF-IDF, then word overlap. Marks are always calculated against the specific question's allocated marks, not the paper total.

---

## Active Learning Pipeline

GEIZMO can grade from day one with no training data, then improves as the lecturer approves good answers.

| Stage | Exemplars per question | Behaviour |
| --- | --- | --- |
| Cold start | 0 | Grades with Sentence-BERT semantic similarity and key points |
| Calibration | 5 or more | Ridge regression is fitted on approved exemplars to match the lecturer's marking style |
| Ongoing | Growing | Each retrain recomputes accuracy metrics and logs them |

A student answer is flagged as a candidate only if it passes four quality gates:

1. Score is at least 90% of the question's marks
2. Answer has at least 10 words
3. Cosine similarity to every existing exemplar is below 0.92 (no near-duplicates)
4. The pending review queue for that question has 10 or fewer items

The lecturer approves or rejects candidates, then clicks **Train Now**. Retraining runs in the background. Only correct answers are used for training, which keeps the exemplar pool clean.

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| Language | Python 3.11 |
| Web framework | Django 4.2 |
| Database | PostgreSQL 15 |
| Semantic model | sentence-transformers 2.2.2 (`all-MiniLM-L6-v2`, about 80 MB) |
| Calibration and fallback | scikit-learn 1.3 (Ridge regression, TF-IDF) |
| Deep learning backend | PyTorch 2.1 |
| File extraction | pdfminer.six (PDF), python-docx (DOCX) |
| Frontend | Vanilla JavaScript (ES2022) and CSS3, no framework |
| Email | Django SMTP backend with a Gmail App Password |
| Timezone | Africa/Gaborone |

---

## Project Structure

```
gizmoDjango/
├── gizmoProject/            # Django settings, root URL config (70+ API routes)
├── apps/
│   └── users/
│       ├── models.py        # 12 models (users, courses, papers, submissions, ...)
│       ├── views.py         # Auth, student, lecturer, admin, AI training and public APIs
│       └── middleware.py    # Maintenance mode middleware
├── gizmo_ai/
│   ├── gizmo_engine.py      # Core grading engine and pipeline classes
│   ├── gizmo_trainer.py     # Ridge regression training and metrics
│   ├── active_learning.py   # Quality gate, approve and reject workflow
│   ├── ai_integration.py    # Bridge between Django submissions and the grader
│   ├── file_extractor.py    # Text extraction from PDF and DOCX
│   └── evaluate.py          # MAE, RMSE, Pearson r, grade band accuracy, key-point F1
├── templates/
│   ├── dashboards/          # Student, lecturer and admin single-page dashboards
│   └── landing/             # Public landing page
├── static/                  # CSS and shared JavaScript (main.js)
├── media/                   # Uploaded files (not tracked in Git)
├── manage.py
├── requirements.txt
├── start.ps1                # Windows helper: activate venv and run the server
└── .env.example             # Template for required environment variables
```

**Database models:** GizmoUser, OTPCode, Course, Enrolment, PastPaper, ModelAnswer, Submission, StudentExemplar, Textbook, StudyMaterial, AITrainingLog, SiteSettings.

---

## Getting Started

### Prerequisites

- Python 3.11
- PostgreSQL 15 or newer
- Git
- A Gmail account with an [App Password](https://support.google.com/accounts/answer/185833) for OTP emails

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/PhazhaChakalisa/geizmo.git
   cd geizmo
   ```

2. **Create and activate a virtual environment**

   Windows (PowerShell):

   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate
   ```

   macOS / Linux:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Cache the Sentence-BERT model** (about 80 MB, so grading works without internet afterwards)

   ```bash
   python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
   ```

5. **Create your `.env` file**

   ```bash
   cp .env.example .env
   ```

   On Windows PowerShell use `Copy-Item .env.example .env`, then fill in the values.

---

## Environment Variables

Configuration is read from a `.env` file in the project root. The file is ignored by Git. See `.env.example` for the exact variable names.

| Setting | Purpose |
| --- | --- |
| Django secret key | Cryptographic signing |
| Debug flag | `True` in development, `False` in production |
| Database credentials | Name, user, password, host and port of PostgreSQL |
| Gmail address and App Password | Sending OTP verification emails |

Never commit real values.

---

## Database Setup

1. Create an empty PostgreSQL database and a user for it.
2. Put the connection details in `.env`.
3. Apply the migrations:

   ```bash
   python manage.py migrate
   ```

4. Create an admin account:

   ```bash
   python manage.py createsuperuser
   ```

---

## Running the App

```bash
python manage.py runserver
```

On Windows you can use the helper script:

```powershell
.\start.ps1
```

Open http://127.0.0.1:8000/ in your browser.

For production, set `DEBUG=False`, configure `ALLOWED_HOSTS`, `STATIC_ROOT` and `MEDIA_ROOT`, and review the limitations below first.

---

## User Roles

| Role | What they can do |
| --- | --- |
| **Student** | Browse enrolled courses and past papers, submit answers, view marks, highlighted errors, feedback and recommended resources, track progress by unique questions attempted |
| **Lecturer** | Manage papers, model answers and key points, review flagged candidate answers, approve or reject exemplars, trigger retraining, view accuracy metrics |
| **Admin** | Manage users and courses, toggle maintenance mode, oversee site settings |

---

## Known Limitations

GEIZMO is a university prototype. Before any public production use, be aware of:

- **No handwriting or scanned PDF support.** Files must contain machine-readable text.
- **No real-time notifications.** The candidate queue and training status need a manual page refresh.
- **Local file storage.** Uploaded files are not stored in the cloud, so horizontal scaling is not supported.
- **Small evaluation dataset.** Metrics were computed on 25 demonstration submissions with no held-out test set, so they are indicative rather than statistically robust.
- **English only.** Equations and source code inside answers are not evaluated semantically.
- **Security hardening needed.** No MIME type validation or virus scanning on uploads, and no rate limiting on public endpoints.

---

## Roadmap

- [ ] Handwriting and scanned document support (OCR)
- [ ] Real-time notifications (WebSockets)
- [ ] Cloud file storage
- [ ] Formal train, validation and test split on a larger dataset
- [ ] Upload validation and rate limiting
- [ ] Multi-language support
- [ ] Automated test suite and deployment guide

---

## Author

**Phazha Chakalisa**
Department of Computer Science, University of Botswana
GitHub: [@PhazhaChakalisa](https://github.com/PhazhaChakalisa)

Developed as a CSI 408 project, supervised by Dr Cleverence Kombe, with Dr Wilson Bakasa as co-supervisor.
