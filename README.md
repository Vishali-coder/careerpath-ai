# CareerPath AI

An AI-powered career guidance web app that generates personalised assessments, learning roadmaps, resumes, and job recommendations based on your skills and interests.

---

## Features

### Core Modules
1. **Register / Login** — Create an account as a Student, School student, or Passed Out professional
2. **Screening Test** — 20 AI-generated MCQ questions (12 on skills, 8 on interests) to determine your learning level
3. **Learning Roadmap** — AI-generated 4-week and 8-week personalised study plans based on your screening result
4. **Progress Test** — 50 AI-generated questions to evaluate your learning (15 skills + 10 interests + 15 skills + 10 general engineering)
5. **AI Resume Generator** — Professional ATS-friendly resume built from your profile, roadmap, and test scores
6. **Job Recommendations** — AI-matched job roles with skill gap analysis based on your profile and assessment level

### Account & Security
- **Password Change** — Change your password from the profile modal (requires current password)
- **Forgot Password** — Token-based password reset flow (1-hour expiry, tokens invalidated after use)
- **Profile Edit** — Update name, skills, interests, education, GitHub, LinkedIn and more

### Admin Panel (`/admin`)
- Dashboard with stats — total users, test counts, average scores, level distribution
- User management — view, reset data, or delete any user
- JSON data export
- Separate admin credentials via environment variables

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| Frontend | Vanilla HTML / CSS / JS (single-page app, no framework) |
| Database | SQLite |
| AI — Primary | Groq (`llama-3.1-8b-instant`) |
| AI — Fallback 1 | Google Gemini (`gemini-2.0-flash`) |
| AI — Fallback 2 | OpenRouter (multiple free models) |

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Add API keys

Edit the `.env` file in the project folder:

```env
GROQ_API_KEY=your_groq_key
GEMINI_API_KEY=your_gemini_key
OPENROUTER_API_KEY=your_openrouter_key

# Optional — change admin credentials (defaults: admin / admin123)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123

# Optional — change Flask secret key in production
SECRET_KEY=your-secret-key
```

Get free API keys:
- **Groq** → https://console.groq.com
- **Gemini** → https://aistudio.google.com/apikey
- **OpenRouter** → https://openrouter.ai/keys

### 3. Run the app

```bash
python app.py
```

Open your browser at **http://localhost:5000**  
Admin panel at **http://localhost:5000/admin**

---

## Free Tier Limits

| Provider | Limit | Resets |
|---|---|---|
| Groq | 30 requests/min | Every minute |
| Gemini | 1,000 requests/day | Midnight |
| OpenRouter | 50 requests/day | Daily |

The app automatically falls back to the next provider when one hits its rate limit. If all three are exhausted, wait 60 seconds and retry.

---

## Project Structure

```
careerpath-main/
├── app.py              # Flask backend — routes, AI logic, DB
├── templates/
│   ├── index.html      # Main frontend (single-page app)
│   └── admin.html      # Admin dashboard
├── requirements.txt    # Python dependencies
├── .env                # API keys (never commit this)
├── careerpath.db       # SQLite database (auto-created, gitignored)
└── README.md
```

---

## API Reference

### Auth
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/register` | Create account |
| POST | `/api/login` | Sign in |
| POST | `/api/logout` | Sign out |

### Profile
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/profile` | Get current user profile |
| PUT | `/api/profile` | Update profile fields |

### Password
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/password/change` | Change password (requires login + current password) |
| POST | `/api/password/forgot` | Request a reset token by email |
| POST | `/api/password/reset` | Reset password using token |

### Assessments
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/questions/screening` | Generate 20 screening questions |
| POST | `/api/questions/screening/submit` | Submit screening answers |
| POST | `/api/questions/progress` | Generate 50 progress questions |
| POST | `/api/questions/progress/submit` | Submit progress answers |
| GET | `/api/history` | Get assessment history |

### Roadmap & Resume
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/roadmap/generate` | Generate 4-week + 8-week roadmap |
| GET | `/api/roadmap` | Get saved roadmap |
| POST | `/api/resume/generate` | Generate AI resume |
| GET | `/api/resume` | Get saved resume |

### Jobs
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/jobs/recommend` | Get 6 AI-matched job roles with skill gap analysis |

### Admin (requires admin session)
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/admin/login` | Admin sign in |
| POST | `/api/admin/logout` | Admin sign out |
| GET | `/api/admin/stats` | Dashboard statistics |
| GET | `/api/admin/users` | List all users |
| GET | `/api/admin/users/<id>` | User detail with assessments |
| DELETE | `/api/admin/users/<id>` | Delete user and all their data |
| POST | `/api/admin/users/<id>/reset` | Reset user's assessment data |
| GET | `/api/admin/export` | Export all data as JSON |

### Utility
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Check AI provider configuration status |

---

## Password Reset Flow

Since this app has no email server, the reset token is returned directly in the API response and displayed on screen for the user to copy.

**In production**, replace the `/api/password/forgot` response to send the token via email instead of returning it in the JSON body.

Tokens expire after **1 hour** and are single-use.

---

## Notes

- The `.env` file is already in `.gitignore` — API keys will not be committed to git
- `careerpath.db` is auto-created on first run — add it to `.gitignore` if you don't want to commit the database
- API keys are permanent until you revoke them — you don't need to change them on every run
- The AI fallback chain means the app keeps working even if one provider is down or rate-limited
