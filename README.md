# Geizmo

An AI-powered answer grading web app built with Django. Geizmo helps educators grade written answers faster and more consistently by using AI to evaluate responses against a marking guide.

> Items in **[square brackets]** are placeholders. Fill them in with the real details of your project before publishing.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Database Setup](#database-setup)
- [Running the App](#running-the-app)
- [Usage](#usage)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Author](#author)

---

## Overview

Grading written answers is slow and often inconsistent between markers. Geizmo aims to reduce that workload by evaluating student answers with AI and returning a score with feedback, while keeping the educator in control of the final result.

**Problem it solves:** [one or two sentences on who the app is for and what pain it removes]

**How grading works:** [short description, for example: the answer is compared with a model answer or rubric, the AI returns a score and reasoning, and the educator can review or override it]

---

## Features

- AI-assisted grading of written answers
- [Marking guide / rubric support]
- [Score and written feedback per answer]
- [User accounts and roles, for example educator and student]
- [Upload of answers or documents (stored in `media/`)]
- [Results history or export]

Edit this list so it matches what the app actually does today.

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | Python, Django |
| Frontend | Django templates, static assets (HTML, CSS, JavaScript) |
| Database | [PostgreSQL / MySQL / SQLite] |
| AI | [AI provider or model used for grading] |
| Configuration | Environment variables via `.env` |

---

## Project Structure

```
gizmoDjango/
├── apps/            # Django apps containing the feature modules
├── gizmo_ai/        # AI grading logic
├── gizmoProject/    # Django project settings and URL configuration
├── media/           # User-uploaded files (not tracked in Git)
├── static/          # Static assets (CSS, JS, images)
├── templates/       # HTML templates
├── manage.py        # Django management entry point
├── requirements.txt # Python dependencies
├── start.ps1        # Helper script: activates the venv and starts the server (Windows)
├── .env.example     # Template for required environment variables
└── README.md
```

---

## Getting Started

### Prerequisites

- Python 3.10 or newer
- Git
- [Database server, if not using SQLite]
- [API key for the AI provider]

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

4. **Create your `.env` file**

   Copy the template and fill in your own values:

   ```bash
   cp .env.example .env
   ```

   On Windows PowerShell use `Copy-Item .env.example .env`.

---

## Environment Variables

The app reads its configuration from a `.env` file in the project root. The file is ignored by Git, so your secrets are never committed. See `.env.example` for the full list of variables.

Typical settings include:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `True` for development, `False` in production |
| Database settings | Name, user, password, host and port of your database |
| AI provider key | API key used for grading |

Never share or commit real values for these.

---

## Database Setup

1. Create an empty database for the project in your database server.
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

Start the development server:

```bash
python manage.py runserver
```

On Windows you can use the helper script, which activates the virtual environment and starts the server:

```powershell
.\start.ps1
```

Then open http://127.0.0.1:8000/ in your browser. The admin panel is at http://127.0.0.1:8000/admin/.

---

## Usage

1. Sign in or create an account.
2. [Create a question and add a marking guide or model answer.]
3. [Submit one or more student answers.]
4. [Review the AI-generated score and feedback, and adjust if needed.]

Add screenshots here once the UI is ready:

```
![Dashboard](docs/screenshots/dashboard.png)
```

---

## Roadmap

- [ ] [Planned feature 1]
- [ ] [Planned feature 2]
- [ ] Automated tests
- [ ] Production deployment guide

---

## Contributing

This is currently a private project. If you have been given access and want to contribute:

1. Create a branch: `git checkout -b feature/your-feature`
2. Commit your changes: `git commit -m "Add your feature"`
3. Push the branch: `git push origin feature/your-feature`
4. Open a pull request

---

## Author

**Phazha Chakalisa**
GitHub: [@PhazhaChakalisa](https://github.com/PhazhaChakalisa)

---

## License

[Choose a license, or state that all rights are reserved.]
