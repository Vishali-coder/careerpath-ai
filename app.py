"""
CareerPath AI — Flask Backend with Multi-Provider AI Fallback
-------------------------------------------------------------
Supports Groq, Google Gemini, and OpenRouter with automatic
fallback when rate limits are hit. All providers are FREE.

Get free API keys:
Groq:       https://console.groq.com
Gemini:     https://aistudio.google.com/apikey
OpenRouter: https://openrouter.ai/keys
"""

from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
from dotenv import load_dotenv
import sqlite3, hashlib, os, json, requests, re, time, secrets
from datetime import datetime, timedelta
from functools import wraps

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "careerpath-dev-secret-2024")
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True
CORS(app, supports_credentials=True)

# ── CONFIG ─────────────────────────────────────────────────────────────────────
# Primary: Groq (fastest, free)
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL      = "llama-3.1-8b-instant"

# Fallback 1: Google Gemini (generous free tier — 15 RPM, 1000 RPD)
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")   # get free key at https://aistudio.google.com/apikey
GEMINI_MODEL    = "gemini-2.0-flash"

# Fallback 2: OpenRouter (25+ free models — 20 RPM, 50 RPD free)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")  # get free key at https://openrouter.ai/keys
OPENROUTER_MODEL   = "google/gemma-3-27b-it:free"

DB_PATH = os.environ.get("DB_PATH", "careerpath.db")

# ── DATABASE ───────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                email         TEXT UNIQUE NOT NULL,
                password      TEXT NOT NULL,
                phone         TEXT,
                user_type     TEXT NOT NULL DEFAULT 'student',
                college       TEXT,
                school        TEXT,
                qualification TEXT,
                experience    TEXT,
                skills        TEXT,
                interests     TEXT,
                github        TEXT,
                linkedin      TEXT,
                is_admin      INTEGER DEFAULT 0,
                created_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS assessments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                type            TEXT NOT NULL,
                score           INTEGER,
                total           INTEGER,
                level           TEXT,
                questions_json  TEXT,
                answers_json    TEXT,
                taken_at        TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS roadmaps (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                level       TEXT NOT NULL,
                weeks_4     TEXT,
                weeks_8     TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS resumes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                content     TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS password_resets (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                token      TEXT UNIQUE NOT NULL,
                expires_at TEXT NOT NULL,
                used       INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)
        # migrate: add is_admin column if it doesn't exist
        try:
            db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        except Exception:
            pass
        # migrate: create password_resets table if it doesn't exist (for existing DBs)
        db.executescript("""
            CREATE TABLE IF NOT EXISTS password_resets (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                token      TEXT UNIQUE NOT NULL,
                expires_at TEXT NOT NULL,
                used       INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)
    print("✅ Database initialised.")

# ── AUTH HELPERS ───────────────────────────────────────────────────────────────
def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Unauthorised. Please log in."}), 401
        return f(*args, **kwargs)
    return decorated

# ── MULTI-PROVIDER AI CLIENT ───────────────────────────────────────────────────
# Tries Groq first → falls back to Gemini → falls back to OpenRouter
# Automatically retries on rate limit (429) errors.

def _call_groq(messages: list, temperature: float) -> str:
    """Call Groq API (OpenAI-compatible endpoint)."""
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": GROQ_MODEL, "messages": messages, "temperature": temperature, "max_tokens": 4096},
        timeout=60,
    )
    if not resp.ok:
        print(f"[Groq] Error {resp.status_code}: {resp.text[:200]}")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()

def _call_gemini(messages: list, temperature: float) -> str:
    """Call Google Gemini API."""
    # Convert OpenAI-style messages to Gemini format
    contents = []
    system_text = ""
    for m in messages:
        if m["role"] == "system":
            system_text = m["content"]
        elif m["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        elif m["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": m["content"]}]})

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096},
    }
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}

    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if not resp.ok:
        print(f"[Gemini] Error {resp.status_code}: {resp.text[:200]}")
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

def _call_openrouter(messages: list, temperature: float) -> str:
    """Call OpenRouter API — tries multiple free models in order."""
    free_models = [
        "openai/gpt-oss-120b:free",
        "openai/gpt-oss-20b:free",
        "google/gemma-3-27b-it:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "meta-llama/llama-3.2-3b-instruct:free",
    ]
    last_err = None
    for model in free_models:
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:5000",
                    "X-Title": "CareerPath AI",
                },
                json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": 4096},
                timeout=60,
            )
            if resp.status_code in (400, 404):
                print(f"[OpenRouter] {model} → {resp.status_code}, trying next...")
                last_err = resp
                continue
            if not resp.ok:
                print(f"[OpenRouter] {model} Error {resp.status_code}: {resp.text[:200]}")
            resp.raise_for_status()
            print(f"[OpenRouter] {model} responded successfully.")
            return resp.json()["choices"][0]["message"]["content"].strip()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status in (400, 404, 429):
                print(f"[OpenRouter] {model} → {status}, trying next...")
                last_err = e
                continue
            raise
    if last_err and hasattr(last_err, 'raise_for_status'):
        last_err.raise_for_status()
    raise last_err or RuntimeError("All OpenRouter models failed")
def ai_generate(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    """
    Smart AI caller with automatic fallback:
      1. Groq (fastest)  — falls back on 429 rate limit
      2. Gemini          — falls back on 429 rate limit
      3. OpenRouter      — last resort
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    providers = []

    if GROQ_API_KEY:
        providers.append(("Groq", _call_groq))
    if GEMINI_API_KEY:
        providers.append(("Gemini", _call_gemini))
    if OPENROUTER_API_KEY:
        providers.append(("OpenRouter", _call_openrouter))

    if not providers:
        raise RuntimeError(
            "No AI API key configured. Set at least one of:\n"
            "  GROQ_API_KEY       → https://console.groq.com\n"
            "  GEMINI_API_KEY     → https://aistudio.google.com/apikey\n"
            "  OPENROUTER_API_KEY → https://openrouter.ai/keys"
        )

    last_error = None
    for name, caller in providers:
        # Groq gets up to 3 retries with backoff on rate limit before moving on
        max_retries = 3 if name == "Groq" else 1
        for attempt in range(1, max_retries + 1):
            try:
                print(f"[AI] Trying {name} (attempt {attempt})...")
                result = caller(messages, temperature)
                print(f"[AI] {name} responded successfully.")
                return result
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status == 429:
                    if attempt < max_retries:
                        wait = attempt * 15  # 15s, 30s
                        print(f"[AI] {name} rate limit hit — retrying in {wait}s...")
                        time.sleep(wait)
                        continue
                    print(f"[AI] {name} rate limit hit — trying next provider...")
                    last_error = f"{name} rate limit hit (429)"
                    break
                elif status == 401:
                    print(f"[AI] {name} invalid API key — trying next provider...")
                    last_error = f"{name} invalid API key (401)"
                    break
                else:
                    print(f"[AI] {name} HTTP error {status} — trying next provider...")
                    last_error = f"{name} HTTP error {status}"
                    break
            except requests.exceptions.ConnectionError:
                print(f"[AI] {name} connection error — trying next provider...")
                last_error = f"{name} connection error"
                break
            except requests.exceptions.Timeout:
                print(f"[AI] {name} timed out — trying next provider...")
                last_error = f"{name} timed out"
                break
            except Exception as e:
                print(f"[AI] {name} unexpected error: {e} — trying next provider...")
                last_error = str(e)
                break

    raise RuntimeError(
        f"All AI providers failed. Last error: {last_error}\n"
        "Tips:\n"
        "  • Add a Gemini key (free, 15 RPM): https://aistudio.google.com/apikey\n"
        "  • Add an OpenRouter key (free): https://openrouter.ai/keys\n"
        "  • Wait 60 seconds and retry (Groq rate limit resets per minute)"
    )

def _recover_truncated_json_array(text: str) -> list:
    """
    Recover a JSON array that was cut off mid-stream by walking back to the
    last successfully closed object and closing the array there.
    """
    # Find the opening bracket
    start = text.find("[")
    if start == -1:
        raise ValueError("No JSON array found")
    text = text[start:]

    # Try progressively shorter slices ending at the last complete '}'
    pos = len(text)
    while pos > 0:
        pos = text.rfind("}", 0, pos)
        if pos == -1:
            break
        candidate = text[: pos + 1].rstrip().rstrip(",") + "]"
        # Remove trailing commas before ] or }
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            result = json.loads(candidate)
            if isinstance(result, list) and len(result) > 0:
                return result
        except json.JSONDecodeError:
            pass
        pos -= 1  # keep searching backwards

    raise ValueError("Could not recover any complete objects from truncated JSON")


def ai_json(prompt: str, system: str = "") -> dict | list:
    """Call AI and parse the response as JSON, with robust truncation recovery."""
    raw = ai_generate(prompt, system, temperature=0.2)
    print("AI RAW:", raw[:500])

    # Strip markdown fences and control characters
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", cleaned)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

    # 1. Try full parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 2. Try recovering a truncated array by walking back to last complete object
    if "[" in cleaned:
        try:
            return _recover_truncated_json_array(cleaned)
        except ValueError:
            pass

    # 3. Try extracting first {...} block (for object responses)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", match.group(0)))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from AI response: {raw[:300]}")
# ── GLOBAL ERROR HANDLERS (always return JSON, never HTML) ───────────────────
@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    print(traceback.format_exc())
    return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def handle_404(e):
    return jsonify({"error": "Not found"}), 404

# ── HEALTH CHECK ──────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    providers = {}
    if GROQ_API_KEY:       providers["groq"]        = f"configured ({GROQ_MODEL})"
    if GEMINI_API_KEY:     providers["gemini"]      = f"configured ({GEMINI_MODEL})"
    if OPENROUTER_API_KEY: providers["openrouter"]  = f"configured ({OPENROUTER_MODEL})"
    if not providers:      providers["warning"]     = "No AI API key set!"
    return jsonify({"flask": "ok", "ai_providers": providers})

# ── REGISTER ──────────────────────────────────────────────────────────────────
@app.route("/api/register", methods=["POST"])
def register():
    data = request.json or {}
    for field in ["name", "email", "password"]:
        if not data.get(field, "").strip():
            return jsonify({"error": f"'{field}' is required."}), 400
    if len(data["password"]) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    with get_db() as db:
        if db.execute("SELECT id FROM users WHERE email = ?", (data["email"].lower(),)).fetchone():
            return jsonify({"error": "Email already registered."}), 409
        db.execute("""
            INSERT INTO users (name,email,password,phone,user_type,college,school,
            qualification,experience,skills,interests,github,linkedin)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["name"].strip(), data["email"].lower().strip(), hash_password(data["password"]),
            data.get("phone",""), data.get("user_type","student"), data.get("college",""),
            data.get("school",""), data.get("qualification",""), data.get("experience",""),
            data.get("skills",""), data.get("interests",""), data.get("github",""), data.get("linkedin",""),
        ))
    return jsonify({"message": "Account created successfully."}), 201

# ── LOGIN ─────────────────────────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def login():
    data     = request.json or {}
    email    = data.get("email", "").lower().strip()
    password = data.get("password", "")
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or user["password"] != hash_password(password):
        return jsonify({"error": "Invalid email or password."}), 401
    session["user_id"] = user["id"]
    return jsonify({"message": "Login successful.", "user": {
        "id": user["id"], "name": user["name"], "email": user["email"],
        "user_type": user["user_type"], "skills": user["skills"], "interests": user["interests"],
        "qualification": user["qualification"], "college": user["college"], "school": user["school"],
        "github": user["github"], "linkedin": user["linkedin"], "phone": user["phone"],
    }})

# ── LOGOUT ────────────────────────────────────────────────────────────────────
@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out."})

# ── PROFILE ───────────────────────────────────────────────────────────────────
@app.route("/api/profile")
@login_required
def profile():
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if not user:
        return jsonify({"error": "User not found."}), 404
    return jsonify(dict(user))

# ── SCREENING QUESTIONS ────────────────────────────────────────────────────────
@app.route("/api/questions/screening", methods=["POST"])
@login_required
def generate_screening_questions():
    data = request.json or {}
    skills = data.get("skills", "")
    interests = data.get("interests", "")
    if not skills and not interests:
        with get_db() as db:
            user = db.execute("SELECT skills, interests FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            skills = user["skills"]; interests = user["interests"]
    system_prompt = "You are a technical assessment AI. Respond with valid JSON only — no markdown, no explanation."
    prompt = f"""You are a quiz generator. Output a JSON array of exactly 20 multiple choice questions.
Topic 1: {skills} — generate 12 questions
Topic 2: {interests} — generate 8 questions

Each object must follow this exact structure:
{{"q":"question text","tag":"topic","difficulty":"easy","options":["A. opt1","B. opt2","C. opt3","D. opt4"],"answer":0,"explanation":"brief reason"}}

Rules:
- "answer" is the 0-based index of the correct option (0, 1, 2, or 3)
- difficulty is one of: easy, medium, hard
- "explanation" must be 10 words or fewer
- Output the JSON array only. No intro text, no markdown.

JSON array:"""
    try:
        questions = ai_json(prompt, system_prompt)
        if not isinstance(questions, list) or len(questions) == 0:
            raise ValueError("Invalid response from AI.")
        questions = questions[:20]
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"questions": questions, "total": len(questions)})

# ── SUBMIT SCREENING ──────────────────────────────────────────────────────────
@app.route("/api/questions/screening/submit", methods=["POST"])
@login_required
def submit_screening():
    data = request.json or {}
    score = data.get("score", 0); total = data.get("total", 20)
    level = "advanced" if score >= 15 else "basic"
    with get_db() as db:
        db.execute("""INSERT INTO assessments (user_id,type,score,total,level,questions_json,answers_json)
            VALUES (?, 'screening', ?, ?, ?, ?, ?)""",
            (session["user_id"], score, total, level,
             json.dumps(data.get("questions",[])), json.dumps(data.get("answers",[]))))
    return jsonify({"level": level, "score": score, "total": total})

# ── GENERATE ROADMAP ──────────────────────────────────────────────────────────
@app.route("/api/roadmap/generate", methods=["POST"])
@login_required
def generate_roadmap():
    data = request.json or {}
    level = data.get("level", "basic")
    skills = data.get("skills", ""); interests = data.get("interests", "")
    if not skills:
        with get_db() as db:
            user = db.execute("SELECT skills, interests FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            skills = user["skills"]; interests = user["interests"]
    system_prompt = "You are a career guidance AI. Respond with valid JSON only — no markdown, no explanation."
    def build_prompt(n):
        depth = "deep, production-ready" if level == "advanced" else "foundational, beginner-friendly"
        return f"""Create a {n}-week {level} learning roadmap for Skills: {skills}, Interests: {interests} ({depth}).
Return ONLY a JSON array with exactly {n} objects:
[{{"week":1,"title":"Title","topics":[{{"name":"Topic","description":"2 sentences.","practice_task":"Task.","project_idea":"Idea.","resources":[{{"title":"Name","url":"https://example.com","type":"article"}}]}}]}}]"""
    try:
        weeks_4 = ai_json(build_prompt(4), system_prompt)
        weeks_8 = ai_json(build_prompt(8), system_prompt)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    with get_db() as db:
        db.execute("DELETE FROM roadmaps WHERE user_id = ?", (session["user_id"],))
        db.execute("INSERT INTO roadmaps (user_id,level,weeks_4,weeks_8) VALUES (?,?,?,?)",
            (session["user_id"], level, json.dumps(weeks_4), json.dumps(weeks_8)))
    return jsonify({"level": level, "weeks_4": weeks_4, "weeks_8": weeks_8})

# ── GET ROADMAP ───────────────────────────────────────────────────────────────
@app.route("/api/roadmap")
@login_required
def get_roadmap():
    with get_db() as db:
        row = db.execute("SELECT * FROM roadmaps WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (session["user_id"],)).fetchone()
    if not row:
        return jsonify({"error": "No roadmap found."}), 404
    return jsonify({"level": row["level"], "weeks_4": json.loads(row["weeks_4"] or "[]"), "weeks_8": json.loads(row["weeks_8"] or "[]")})

# ── PROGRESS QUESTIONS ────────────────────────────────────────────────────────
@app.route("/api/questions/progress", methods=["POST"])
@login_required
def generate_progress_questions():
    data = request.json or {}
    skills = data.get("skills", ""); interests = data.get("interests", ""); level = data.get("level", "basic")
    if not skills:
        with get_db() as db:
            user = db.execute("SELECT skills, interests FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            skills = user["skills"]; interests = user["interests"]
    system_prompt = "You are a technical assessment AI. Respond with valid JSON only — no markdown, no explanation."

    def make_prompt(topic, tag, count):
        return f"""Generate exactly {count} MCQ questions on: {topic} (intermediate-advanced level).
Level completed: {level}. Return ONLY a JSON array of exactly {count} objects:
[{{"q":"Question?","tag":"{tag}","difficulty":"medium","options":["A. a","B. b","C. c","D. d"],"answer":0,"explanation":"10 words max."}}]"""

    try:
        # Batch 1: 15 skills + 10 interests
        batch1 = ai_json(make_prompt(skills, skills, 15), system_prompt)
        if not isinstance(batch1, list): batch1 = []

        batch2 = ai_json(make_prompt(interests, interests, 10), system_prompt)
        if not isinstance(batch2, list): batch2 = []

        # Batch 2: 15 skills + 10 general
        batch3 = ai_json(make_prompt(skills, skills, 15), system_prompt)
        if not isinstance(batch3, list): batch3 = []

        batch4 = ai_json(make_prompt("general software engineering: algorithms, data structures, OOP, databases, system design", "General", 10), system_prompt)
        if not isinstance(batch4, list): batch4 = []

        questions = (batch1 + batch2 + batch3 + batch4)[:50]

        if len(questions) < 10:
            raise ValueError("Not enough questions generated. Please retry.")

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"questions": questions, "total": len(questions)})

# ── SUBMIT PROGRESS ───────────────────────────────────────────────────────────
@app.route("/api/questions/progress/submit", methods=["POST"])
@login_required
def submit_progress():
    data = request.json or {}
    score = data.get("score", 0); total = data.get("total", 50)
    pct = round((score / total) * 100) if total else 0
    with get_db() as db:
        db.execute("""INSERT INTO assessments (user_id,type,score,total,level,answers_json)
            VALUES (?, 'progress', ?, ?, ?, ?)""",
            (session["user_id"], score, total,
            "expert" if pct >= 80 else "proficient" if pct >= 60 else "developing",
            json.dumps(data.get("answers",[]))))
    return jsonify({"score": score, "total": total, "percentage": pct})

# ── GENERATE RESUME ───────────────────────────────────────────────────────────
@app.route("/api/resume/generate", methods=["POST"])
@login_required
def generate_resume():
    with get_db() as db:
        user      = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        screening = db.execute("SELECT score,total,level FROM assessments WHERE user_id=? AND type='screening' ORDER BY taken_at DESC LIMIT 1", (session["user_id"],)).fetchone()
        progress  = db.execute("SELECT score,total FROM assessments WHERE user_id=? AND type='progress' ORDER BY taken_at DESC LIMIT 1", (session["user_id"],)).fetchone()
        roadmap   = db.execute("SELECT level,weeks_4 FROM roadmaps WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (session["user_id"],)).fetchone()
    if not user:
        return jsonify({"error": "User not found."}), 404
    roadmap_summary = ""
    if roadmap:
        weeks = json.loads(roadmap["weeks_4"] or "[]")
        roadmap_summary = "\n".join(f"Week {w.get('week','?')}: {w.get('title','')}" for w in weeks)
    system_prompt = "You are a professional resume writer for tech careers. Write ATS-friendly content. Respond with valid JSON only."
    prompt = f"""Write a detailed, professional tech resume for this candidate:

Name: {user['name']}
Email: {user['email']}
Phone: {user['phone']}
College/School: {user['college'] or user['school']}
Qualification: {user['qualification']}
Experience: {user['experience'] or 'Fresher'}
Skills: {user['skills']}
Interests: {user['interests']}
GitHub: {user['github']}
LinkedIn: {user['linkedin']}
Screening Score: {screening['score'] if screening else 'N/A'}/{screening['total'] if screening else 20} (Level: {screening['level'] if screening else 'N/A'})
Progress Score: {progress['score'] if progress else 'N/A'}/{progress['total'] if progress else 50}
Learning Roadmap Completed: {roadmap_summary or 'Not completed'}

Return ONLY this JSON with rich, detailed content:
{{
  "summary": "3-sentence ATS-optimised professional summary highlighting skills, experience level, and career goal",
  "skills": ["skill1", "skill2", "skill3", "skill4", "skill5", "skill6", "skill7", "skill8"],
  "technical_skills": {{
    "languages": ["lang1", "lang2"],
    "frameworks": ["fw1", "fw2"],
    "tools": ["tool1", "tool2"],
    "databases": ["db1"]
  }},
  "education": [
    {{"degree": "...", "institution": "...", "year": "...", "gpa": "...", "relevant_courses": ["course1", "course2"]}}
  ],
  "experience": [
    {{"title": "...", "company": "...", "duration": "...", "points": ["achievement 1 with metric", "achievement 2"]}}
  ],
  "projects": [
    {{"title": "...", "tech_stack": "...", "description": "2 sentences describing what it does and impact.", "github_link": ""}}
  ],
  "achievements": ["achievement with context 1", "achievement 2", "achievement 3"],
  "certifications": ["cert 1", "cert 2"],
  "soft_skills": ["skill1", "skill2", "skill3", "skill4"],
  "languages_known": ["English", "Tamil"],
  "career_objective": "2-sentence targeted career objective for the role they want"
}}"""
    try:
        resume_data = ai_json(prompt, system_prompt)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    resume_data.update({"name": user["name"], "email": user["email"], "phone": user["phone"],
                        "github": user["github"], "linkedin": user["linkedin"],
                        "generated_at": datetime.now().isoformat()})
    with get_db() as db:
        db.execute("INSERT INTO resumes (user_id,content) VALUES (?,?)", (session["user_id"], json.dumps(resume_data)))
    return jsonify(resume_data)

# ── GET RESUME ────────────────────────────────────────────────────────────────
@app.route("/api/resume")
@login_required
def get_resume():
    with get_db() as db:
        row = db.execute("SELECT content FROM resumes WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (session["user_id"],)).fetchone()
    if not row:
        return jsonify({"error": "No resume found."}), 404
    return jsonify(json.loads(row["content"]))

# ── UPDATE PROFILE ────────────────────────────────────────────────────────────
@app.route("/api/profile", methods=["PUT"])
@login_required
def update_profile():
    data = request.json or {}
    allowed = ["name", "phone", "college", "school", "qualification",
               "experience", "skills", "interests", "github", "linkedin"]
    updates = {k: data[k].strip() for k in allowed if k in data}
    if not updates:
        return jsonify({"error": "No fields to update."}), 400
    if "name" in updates and not updates["name"]:
        return jsonify({"error": "Name cannot be empty."}), 400
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [session["user_id"]]
    with get_db() as db:
        db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return jsonify({"message": "Profile updated.", "user": dict(user)})

# ── CHANGE PASSWORD ───────────────────────────────────────────────────────────
@app.route("/api/password/change", methods=["POST"])
@login_required
def change_password():
    data = request.json or {}
    current_pw  = data.get("current_password", "")
    new_pw      = data.get("new_password", "")
    confirm_pw  = data.get("confirm_password", "")
    if not current_pw or not new_pw or not confirm_pw:
        return jsonify({"error": "All fields are required."}), 400
    if len(new_pw) < 8:
        return jsonify({"error": "New password must be at least 8 characters."}), 400
    if new_pw != confirm_pw:
        return jsonify({"error": "New passwords do not match."}), 400
    with get_db() as db:
        user = db.execute("SELECT password FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not user or user["password"] != hash_password(current_pw):
            return jsonify({"error": "Current password is incorrect."}), 401
        db.execute("UPDATE users SET password=? WHERE id=?", (hash_password(new_pw), session["user_id"]))
    return jsonify({"message": "Password changed successfully."})

# ── FORGOT PASSWORD ───────────────────────────────────────────────────────────
@app.route("/api/password/forgot", methods=["POST"])
def forgot_password():
    data  = request.json or {}
    email = data.get("email", "").lower().strip()
    if not email:
        return jsonify({"error": "Email is required."}), 400
    with get_db() as db:
        user = db.execute("SELECT id, name FROM users WHERE email=?", (email,)).fetchone()
        if not user:
            # Don't reveal whether the email exists
            return jsonify({"message": "If that email is registered, a reset token has been generated."}), 200
        # Invalidate any existing unused tokens for this user
        db.execute("UPDATE password_resets SET used=1 WHERE user_id=? AND used=0", (user["id"],))
        token      = secrets.token_urlsafe(32)
        expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
        db.execute(
            "INSERT INTO password_resets (user_id, token, expires_at) VALUES (?,?,?)",
            (user["id"], token, expires_at)
        )
    # In a real app you'd email this token. Here we return it directly
    # so the user can use it without an email server.
    return jsonify({
        "message": "Reset token generated. Use it within 1 hour.",
        "reset_token": token,
        "note": "In production, this token would be emailed. Copy it and use the reset form."
    }), 200

# ── RESET PASSWORD ────────────────────────────────────────────────────────────
@app.route("/api/password/reset", methods=["POST"])
def reset_password():
    data        = request.json or {}
    token       = data.get("token", "").strip()
    new_pw      = data.get("new_password", "")
    confirm_pw  = data.get("confirm_password", "")
    if not token or not new_pw or not confirm_pw:
        return jsonify({"error": "All fields are required."}), 400
    if len(new_pw) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if new_pw != confirm_pw:
        return jsonify({"error": "Passwords do not match."}), 400
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM password_resets WHERE token=? AND used=0",
            (token,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Invalid or already used reset token."}), 400
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            return jsonify({"error": "Reset token has expired. Please request a new one."}), 400
        db.execute("UPDATE users SET password=? WHERE id=?", (hash_password(new_pw), row["user_id"]))
        db.execute("UPDATE password_resets SET used=1 WHERE token=?", (token,))
    return jsonify({"message": "Password reset successfully. You can now log in."})

# ── HISTORY ───────────────────────────────────────────────────────────────────
@app.route("/api/history")
@login_required
def history():
    with get_db() as db:
        assessments = db.execute("SELECT type,score,total,level,taken_at FROM assessments WHERE user_id=? ORDER BY taken_at DESC", (session["user_id"],)).fetchall()
    return jsonify({"assessments": [dict(a) for a in assessments]})

# ── ADMIN AUTH ────────────────────────────────────────────────────────────────
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "Admin access required."}), 403
        return f(*args, **kwargs)
    return decorated

# ── ADMIN LOGIN ───────────────────────────────────────────────────────────────
@app.route("/admin")
def admin_page():
    return render_template("admin.html")

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.json or {}
    if data.get("username") == ADMIN_USERNAME and data.get("password") == ADMIN_PASSWORD:
        session["is_admin"] = True
        return jsonify({"message": "Admin login successful."})
    return jsonify({"error": "Invalid admin credentials."}), 401

@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return jsonify({"message": "Logged out."})

# ── ADMIN STATS ───────────────────────────────────────────────────────────────
@app.route("/api/admin/stats")
@admin_required
def admin_stats():
    with get_db() as db:
        total_users     = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_screening = db.execute("SELECT COUNT(*) FROM assessments WHERE type='screening'").fetchone()[0]
        total_progress  = db.execute("SELECT COUNT(*) FROM assessments WHERE type='progress'").fetchone()[0]
        total_roadmaps  = db.execute("SELECT COUNT(*) FROM roadmaps").fetchone()[0]
        total_resumes   = db.execute("SELECT COUNT(*) FROM resumes").fetchone()[0]
        avg_screening   = db.execute("SELECT AVG(CAST(score AS FLOAT)/total*100) FROM assessments WHERE type='screening' AND total>0").fetchone()[0]
        avg_progress    = db.execute("SELECT AVG(CAST(score AS FLOAT)/total*100) FROM assessments WHERE type='progress' AND total>0").fetchone()[0]
        advanced_count  = db.execute("SELECT COUNT(*) FROM assessments WHERE type='screening' AND level='advanced'").fetchone()[0]
        basic_count     = db.execute("SELECT COUNT(*) FROM assessments WHERE type='screening' AND level='basic'").fetchone()[0]
        user_types      = db.execute("SELECT user_type, COUNT(*) as cnt FROM users GROUP BY user_type").fetchall()
        recent_users    = db.execute("SELECT name, email, created_at FROM users ORDER BY created_at DESC LIMIT 5").fetchall()
    return jsonify({
        "total_users": total_users,
        "total_screening": total_screening,
        "total_progress": total_progress,
        "total_roadmaps": total_roadmaps,
        "total_resumes": total_resumes,
        "avg_screening_pct": round(avg_screening or 0, 1),
        "avg_progress_pct": round(avg_progress or 0, 1),
        "advanced_count": advanced_count,
        "basic_count": basic_count,
        "user_types": [dict(r) for r in user_types],
        "recent_users": [dict(r) for r in recent_users],
    })

# ── ADMIN USERS LIST ──────────────────────────────────────────────────────────
@app.route("/api/admin/users")
@admin_required
def admin_users():
    with get_db() as db:
        users = db.execute("""
            SELECT u.id, u.name, u.email, u.phone, u.user_type,
                   u.college, u.school, u.qualification, u.skills, u.interests,
                   u.github, u.linkedin, u.created_at,
                   (SELECT COUNT(*) FROM assessments a WHERE a.user_id=u.id) as assessment_count,
                   (SELECT COUNT(*) FROM roadmaps r WHERE r.user_id=u.id) as roadmap_count,
                   (SELECT COUNT(*) FROM resumes rs WHERE rs.user_id=u.id) as resume_count,
                   (SELECT level FROM assessments a WHERE a.user_id=u.id AND a.type='screening' ORDER BY a.taken_at DESC LIMIT 1) as level
            FROM users u ORDER BY u.created_at DESC
        """).fetchall()
    return jsonify({"users": [dict(u) for u in users]})

# ── ADMIN USER DETAIL ─────────────────────────────────────────────────────────
@app.route("/api/admin/users/<int:uid>")
@admin_required
def admin_user_detail(uid):
    with get_db() as db:
        user        = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        assessments = db.execute("SELECT type,score,total,level,taken_at FROM assessments WHERE user_id=? ORDER BY taken_at DESC", (uid,)).fetchall()
        roadmap     = db.execute("SELECT level,created_at FROM roadmaps WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (uid,)).fetchone()
        resume      = db.execute("SELECT created_at FROM resumes WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (uid,)).fetchone()
    if not user:
        return jsonify({"error": "User not found."}), 404
    return jsonify({
        "user": dict(user),
        "assessments": [dict(a) for a in assessments],
        "roadmap": dict(roadmap) if roadmap else None,
        "resume": dict(resume) if resume else None,
    })

# ── ADMIN DELETE USER ─────────────────────────────────────────────────────────
@app.route("/api/admin/users/<int:uid>", methods=["DELETE"])
@admin_required
def admin_delete_user(uid):
    with get_db() as db:
        db.execute("DELETE FROM assessments WHERE user_id=?", (uid,))
        db.execute("DELETE FROM roadmaps WHERE user_id=?", (uid,))
        db.execute("DELETE FROM resumes WHERE user_id=?", (uid,))
        db.execute("DELETE FROM users WHERE id=?", (uid,))
    return jsonify({"message": "User deleted."})

# ── ADMIN RESET USER DATA ─────────────────────────────────────────────────────
@app.route("/api/admin/users/<int:uid>/reset", methods=["POST"])
@admin_required
def admin_reset_user(uid):
    with get_db() as db:
        db.execute("DELETE FROM assessments WHERE user_id=?", (uid,))
        db.execute("DELETE FROM roadmaps WHERE user_id=?", (uid,))
        db.execute("DELETE FROM resumes WHERE user_id=?", (uid,))
    return jsonify({"message": "User data reset."})

# ── ADMIN EXPORT ──────────────────────────────────────────────────────────────
@app.route("/api/admin/export")
@admin_required
def admin_export():
    with get_db() as db:
        users = db.execute("SELECT id,name,email,phone,user_type,college,school,qualification,skills,interests,created_at FROM users").fetchall()
        assessments = db.execute("SELECT user_id,type,score,total,level,taken_at FROM assessments").fetchall()
    return jsonify({
        "users": [dict(u) for u in users],
        "assessments": [dict(a) for a in assessments],
        "exported_at": datetime.now().isoformat(),
    })

# ── JOB RECOMMENDATIONS ──────────────────────────────────────────────────────
@app.route("/api/jobs/recommend", methods=["POST"])
@login_required
def job_recommendations():
    with get_db() as db:
        user      = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        screening = db.execute(
            "SELECT score,total,level FROM assessments WHERE user_id=? AND type='screening' ORDER BY taken_at DESC LIMIT 1",
            (session["user_id"],)
        ).fetchone()
        progress  = db.execute(
            "SELECT score,total FROM assessments WHERE user_id=? AND type='progress' ORDER BY taken_at DESC LIMIT 1",
            (session["user_id"],)
        ).fetchone()
    if not user:
        return jsonify({"error": "User not found."}), 404

    level     = screening["level"] if screening else "basic"
    scr_pct   = round(screening["score"] / screening["total"] * 100) if screening and screening["total"] else 0
    prog_pct  = round(progress["score"]  / progress["total"]  * 100) if progress  and progress["total"]  else 0

    system_prompt = (
        "You are a career advisor AI. Respond with valid JSON only — no markdown, no explanation."
    )
    prompt = f"""You are a career advisor. Based on the candidate profile below, recommend exactly 6 job roles.

Candidate Profile:
- Skills: {user['skills'] or 'Not specified'}
- Interests: {user['interests'] or 'Not specified'}
- Qualification: {user['qualification'] or 'Not specified'}
- Experience: {user['experience'] or 'Fresher'}
- Assessment Level: {level}
- Screening Score: {scr_pct}%
- Progress Score: {prog_pct}%

Return ONLY a JSON array of exactly 6 objects with this exact structure:
[
  {{
    "title": "Job Role Title",
    "match_pct": 85,
    "category": "one of: Best Match, Strong Match, Good Match, Stretch Goal",
    "why": "2 sentences explaining why this role suits the candidate.",
    "required_skills": ["skill1", "skill2", "skill3", "skill4", "skill5"],
    "candidate_has": ["skill1", "skill2"],
    "skill_gaps": ["missing_skill1", "missing_skill2", "missing_skill3"],
    "avg_salary": "₹4–8 LPA",
    "time_to_ready": "2–3 months",
    "top_companies": ["Company A", "Company B", "Company C"]
  }}
]

Rules:
- Sort by match_pct descending (highest first)
- First 2 should be "Best Match", next 2 "Strong Match", last 2 "Good Match" or "Stretch Goal"
- skill_gaps must only list skills the candidate does NOT already have
- candidate_has must only list skills from required_skills that the candidate already has
- Output the JSON array only. No intro text, no markdown fences."""

    try:
        jobs = ai_json(prompt, system_prompt)
        if not isinstance(jobs, list) or len(jobs) == 0:
            raise ValueError("Invalid response from AI.")
        jobs = jobs[:6]
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"jobs": jobs, "level": level, "scr_pct": scr_pct, "prog_pct": prog_pct})

# ── SERVE FRONTEND ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# ── INIT DB ON STARTUP (works with both gunicorn and python app.py) ───────────
init_db()

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("── AI Provider Status ──────────────────────────")
    if GROQ_API_KEY:
        print(f"✅ Groq        : {GROQ_API_KEY[:12]}...  (primary)")
    else:
        print("⚠️  Groq        : NOT SET  → https://console.groq.com")
    if GEMINI_API_KEY:
        print(f"✅ Gemini      : {GEMINI_API_KEY[:12]}...  (fallback 1)")
    else:
        print("⚠️  Gemini      : NOT SET  → https://aistudio.google.com/apikey")
    if OPENROUTER_API_KEY:
        print(f"✅ OpenRouter  : {OPENROUTER_API_KEY[:12]}...  (fallback 2)")
    else:
        print("⚠️  OpenRouter  : NOT SET  → https://openrouter.ai/keys")
    if not any([GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY]):
        print("❌ No API keys set! App will not work.")
    print("────────────────────────────────────────────────")
    print("🚀 CareerPath AI running at http://localhost:5000")
    app.run(debug=True, port=5000)
