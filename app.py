import os
import json
import base64
import re
import io
from unittest import result
import pdfplumber
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types
from dotenv import load_dotenv
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

load_dotenv()

from authenticate import create_user, verify_user, create_session, get_user_from_token, find_or_create_google_user
from database import init_db, get_connection
from course_data import get_courses_for_skill


def is_password_valid(password):
    """Enforces: min 8 chars, 1 uppercase, 1 lowercase, 1 special character."""
    if len(password) < 8:
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=~`\[\]\\/;']", password):
        return False
    return True


def extract_cv_text(pdf_bytes):
    """Extracts plain text from a PDF's bytes. Returns an empty string if
    extraction fails for any reason (e.g. a scanned/image-only PDF)."""
    try:
        text_parts = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return " ".join(text_parts)
    except Exception:
        return ""

# Common variations so "SQL" also matches "MySQL", "structured query
# language", etc. — handles abbreviation mismatches that share no
# common root word, which generic word-matching alone can't catch.
SKILL_TEXT_ALIASES = {
    "sql": ["sql", "mysql", "postgresql", "structured query language", "queries", "joins"],
    "javascript": ["javascript", "js"],
    "flask": ["flask"],
    "django": ["django"],
    "python web frameworks": ["flask", "django"],
    "backend apis": ["flask", "django", "rest api", "api integration", "crud"],
    "rest api": ["rest api", "rest apis", "api integration", "restful"],
    "git": ["git", "github", "version control"],
    "version control": ["git", "github", "version control"],
    "relational databases": ["sql", "mysql", "postgresql"],
    "docker": ["docker"],
    "agile": ["agile", "scrum", "jira"],
    "jira": ["jira"],
    "cloud platforms": ["aws", "azure", "gcp", "cloud"],
    "ci/cd": ["ci/cd", "continuous integration", "continuous deployment"],
}

# Common filler words to ignore when comparing skill names against CV
# text, so matching focuses on meaningful terms rather than sentence glue.
STOPWORDS = {
    "a", "an", "and", "the", "or", "in", "on", "with", "using", "for",
    "to", "of", "including", "e.g", "etc", "based", "design", "skills",
    "experience", "understanding", "knowledge", "familiarity", "basic",
    "strong", "solid", "ability", "work", "build", "maintain",
}


def _meaningful_words(text):
    """Splits text into lowercase words, stripping punctuation and
    removing common filler words that don't carry real skill meaning."""
    words = re.findall(r"[a-z0-9\+\#\.]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def reconcile_missing_skills(cv_text, result):
    """Safety net: if a skill Gemini marked as 'missing' is actually
    mentioned in the CV text, move it to 'skills_partial' instead.
    Uses two layers of matching so this works across any field, not
    just tech skills we specifically anticipated:
      1. Known aliases (SKILL_TEXT_ALIASES) for abbreviation mismatches
         like SQL <-> MySQL that share no common root word.
      2. Generic word-overlap matching, which works for any skill in
         any domain by comparing meaningful words against the CV text.
    """
    if not cv_text:
        return result

    cv_text_lower = cv_text.lower()
    still_missing = []
    moved = []

    for skill in result.get("skills_missing", []):
        skill_lower = skill.lower()

        # Layer 1: known aliases
        aliases_to_check = [skill_lower]
        for key, variants in SKILL_TEXT_ALIASES.items():
            if key in skill_lower:
                aliases_to_check.extend(variants)
        found_via_alias = any(alias in cv_text_lower for alias in aliases_to_check)

        # Layer 2: generic word-overlap matching (works for any field)
        skill_words = _meaningful_words(skill)
        found_via_words = False
        if skill_words:
            matched_words = [w for w in skill_words if w in cv_text_lower]
            found_via_words = len(matched_words) / len(skill_words) >= 0.6

        if found_via_alias or found_via_words:
            moved.append(skill)
        else:
            still_missing.append(skill)

    result["skills_missing"] = still_missing
    result["skills_partial"] = result.get("skills_partial", []) + moved

    return result

GOOGLE_CLIENT_ID = "235368564033-rt6pgea9p6orn1nu2qnbuv88n3m7dq44.apps.googleusercontent.com"
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY not found. Create a .env file with GEMINI_API_KEY=your_key_here"
    )

client = genai.Client(api_key=API_KEY)

app = Flask(__name__)
CORS(app)

init_db()

MODEL_NAME = "gemini-2.5-flash"

PROMPT_TEMPLATE = """You are an expert career advisor specialising in Pakistan's job market (Rozee.pk, LinkedIn Pakistan, local tech industry).

You will be given a candidate's CV (as an attached PDF document) and a job description (as text below).

Your task:
1. Read and understand the CV content from the attached PDF.
2. Compare it against the job description.
3. Calculate an honest match score (0-100) based on how well the candidate's skills, experience, and qualifications align with the job requirements.
4. Identify which required skills the candidate clearly has, which they partially have, and which are completely missing.
4b. CRITICAL: Before marking any skill as "missing," search the CV text character-by-character for that exact skill name or a close synonym. If ANY internship, project, or coursework entry contains that word or technology name — regardless of duration, depth, or how it's phrased — you MUST classify it as "present," not "missing." Under no circumstances should real, named experience be omitted for being "too brief." This rule overrides your own judgment about sufficiency.
5. Order the missing/partial skills by learning priority - which skill should be learned first, second, etc, based on importance to the job and typical prerequisites (foundational skills first).
5b. If the candidate is currently pursuing a degree relevant to the requirement (e.g. "Bachelor's in Computer Science 2024–Present"), treat that requirement as FOUND (not missing) if the role targets students/fresh graduates (look for phrases like "fresh graduates encouraged," "0-1 years experience," "entry-level," "internship"). Only mark a degree requirement as missing if the CV shows no relevant enrollment or completion at all, or if the JD explicitly requires a completed/conferred degree.
6. Give specific, actionable tips to improve the CV itself (wording, structure, missing sections, quantifying achievements, etc).

Respond with ONLY valid JSON. No markdown formatting, no code fences, no explanation outside the JSON.

JOB DESCRIPTION:
{jd}

Return exactly this JSON structure:
{{
  "score": <integer 0-100, overall match percentage>,
  "verdict": "<short 5-8 word verdict, e.g. 'Strong candidate with minor gaps'>",
  "summary": "<2-3 sentence honest, specific summary of fit, referencing actual CV content>",
  "skills_present": ["<skill the candidate clearly has>", ...],
  "skills_partial": ["<skill candidate has some exposure to but not strong>", ...],
  "skills_missing": ["<skill required by JD but absent from CV, ordered by learning priority - most important/foundational first>", ...],
  "keywords": [
    {{"word": "<important keyword/skill from JD>", "found": <true|false>, "importance": <1-10, how critical this is to the role>}},
    ... (top 8 most important keywords from the JD, ranked by importance)
  ],
  "cv_tips": [
    "<specific actionable tip referencing what's actually in/missing from their CV>",
    ... (4-6 tips)
  ]
}}
"""


@app.route("/api/signup", methods=["POST"])
@app.route("/api/register", methods=["POST"])
def signup():
    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"message": "Email and password are required."}), 400
    if not is_password_valid(password):
        return jsonify({
            "message": "Password must be at least 8 characters and include 1 uppercase letter, 1 lowercase letter, and 1 special character."
        }), 400

    user_id = create_user(email, password)
    if not user_id:
        return jsonify({"message": "An account with this email already exists."}), 409

    token = create_session(user_id)
    return jsonify({
        "message": "Account created successfully.",
        "token": token,
        "is_paid": False,
        "success": True
    }), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"message": "Email and password are required."}), 400

    user = verify_user(email, password)
    if not user:
        return jsonify({"message": "Incorrect email or password."}), 401

    token = create_session(user["id"])
    return jsonify({
        "message": "Logged in successfully.",
        "token": token,
        "is_paid": bool(user["is_paid"])
    }), 200


@app.route("/api/upgrade", methods=["POST"])
def upgrade():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = get_user_from_token(token)

    if not user:
        return jsonify({"message": "Not logged in."}), 401

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET is_paid = 1 WHERE id = %s", (user["id"],)
    )
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({
        "message": "Upgrade successful! Learning pathway unlocked.",
        "is_paid": True
    }), 200


@app.route("/api/analyse", methods=["POST"])
def analyse():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user = get_user_from_token(token)

    if not user:
        return jsonify({"message": "Please log in to analyse your CV."}), 401

    is_paid = bool(user["is_paid"])

    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"message": "Invalid request body."}), 400

    cv_file_b64 = data.get("cvFile")
    cv_file_name = data.get("cvFileName", "cv.pdf")
    jd = data.get("jd", "").strip()

    if not cv_file_b64:
        return jsonify({"message": "No CV file provided."}), 400
    if not jd:
        return jsonify({"message": "No job description provided."}), 400
    if len(jd) < 50:
        return jsonify({"message": "Job description is too short."}), 400

    try:
        pdf_bytes = base64.b64decode(cv_file_b64)
    except Exception:
        return jsonify({"message": "Could not decode the uploaded CV file."}), 400

    prompt_text = PROMPT_TEMPLATE.format(jd=jd)

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=prompt_text),
                        types.Part.from_bytes(
                            data=pdf_bytes,
                            mime_type="application/pdf",
                        ),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=8000,
            ),
        )
    except Exception as e:
        return jsonify({"message": f"Gemini API error: {str(e)}"}), 502

    raw_text = (response.text or "").strip()
    raw_text = raw_text.replace("```json", "").replace("```", "").strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        return jsonify({
            "message": "Gemini returned an unexpected format. Please try again.",
            "raw": raw_text[:500]
        }), 502

    cv_text = extract_cv_text(pdf_bytes)
    result = reconcile_missing_skills(cv_text, result)

    gap_skills = result.get("skills_missing", []) + result.get("skills_partial", [])

    # Courses list — shown to everyone, free or paid
    seen_urls = set()
    courses = []
    for skill in gap_skills:
        for course in get_courses_for_skill(skill):
            if course["url"] not in seen_urls:
                courses.append(course)
                seen_urls.add(course["url"])
    result["courses"] = courses

    # Learning pathway — ordered, step-by-step, paid users only
    if not is_paid:
        result["learning_pathway"] = None
        result["pathway_locked"] = True
    else:
        seen_urls_pathway = set()
        pathway = []
        for skill in gap_skills:
            unique_courses = []
            for course in get_courses_for_skill(skill):
                if course["url"] not in seen_urls_pathway:
                    unique_courses.append(course)
                    seen_urls_pathway.add(course["url"])
            if unique_courses:
                pathway.append({"skill": skill, "courses": unique_courses})
        result["learning_pathway"] = pathway
        result["pathway_locked"] = False

    return jsonify(result), 200

@app.route("/api/google-login", methods=["POST"])
def google_login():
    data = request.get_json(force=True)
    credential = data.get("credential")

    if not credential:
        return jsonify({"message": "No Google credential provided."}), 400

    try:
        idinfo = id_token.verify_oauth2_token(
            credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        return jsonify({"message": "Invalid Google credential."}), 401

    email = idinfo.get("email", "").strip().lower()
    if not email:
        return jsonify({"message": "Google account has no email."}), 400

    user = find_or_create_google_user(email)
    token = create_session(user["id"])

    return jsonify({
        "message": "Logged in with Google.",
        "token": token,
        "email": email,
        "is_paid": bool(user["is_paid"])
    }), 200

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model": MODEL_NAME}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)