# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import datetime
import bcrypt
import os
import requests
import re
import json
import io
import pdfplumber
from docx import Document

load_dotenv()

app = Flask(__name__)
CORS(app)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

USERS_FILE = "users.json"
HISTORY_FILE = "history.json"


# ==================================================
# HELPERS
# ==================================================
def load_json(filename):
    if not os.path.exists(filename):
        with open(filename, "w") as f:
            json.dump([], f)
    with open(filename, "r") as f:
        return json.load(f)


def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)


def ask_ollama(prompt):
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "tinyllama", "prompt": prompt, "stream": False},
        timeout=90
    )
    return response.json()["response"]


def is_resume(text):
    """
    Returns (True, None) if text looks like a resume.
    Returns (False, reason) if it looks like something else.
    """
    t = text.lower()

    # Hard-stop patterns — these strongly indicate non-resume docs
    non_resume_signals = [
        # Offer / appointment letters
        "offer letter", "pleased to offer", "dear candidate",
        "joining date", "appointment letter", "terms and conditions",
        "probation period", "annual package", "ctc", "payroll",
        "congratulations on your selection",
        # Financial / legal docs
        "invoice", "receipt", "purchase order", "bill to",
        "payment due", "tax invoice", "total amount",
        "to whomsoever it may concern", "this is to certify",
        "reference number", "policy number", "loan agreement",
        "legal notice", "court order", "affidavit",
        # Project reports / internship reports / academic docs
        "project abstract", "problem statement", "proposed system",
        "system architecture", "feasibility analysis", "project timeline",
        "future enhancements", "system modules", "objectives of the project",
        "technologies used", "expected outcome", "project title",
        "submitted by", "declaration", "usn", "college name",
        "internship report", "project report", "minor project",
        "major project", "phase 1", "phase 2", "requirement analysis",
        "system design", "baseline implementation", "literature review",
        "abstract", "acknowledgement", "table of contents",
        "list of figures", "chapter 1", "chapter 2",
        # Certificates / marksheets
        "this is to certify that", "has successfully completed",
        "marks obtained", "grade sheet", "transcript",
        "semester", "subject code", "internal marks"
    ]

    # Positive resume indicators — must have PERSONAL career info
    resume_signals = [
        "work experience", "professional experience", "employment history",
        "education", "objective", "career objective", "professional summary",
        "certifications", "achievements", "worked at", "worked with",
        "bachelor of", "master of", "b.e", "b.tech", "m.tech", "mba",
        "gpa", "cgpa", "resume", "curriculum vitae", "c.v",
        "references", "hobbies", "languages known", "date of birth",
        "contact", "linkedin", "github", "portfolio",
        "responsible for", "developed", "implemented", "designed",
        "led", "managed", "internship at", "trained at"
    ]

    non_resume_hits = sum(1 for s in non_resume_signals if s in t)
    resume_hits = sum(1 for s in resume_signals if s in t)

    if non_resume_hits >= 2:
        return False, "This looks like a project report, offer letter, invoice, or official document — not a resume."

    if resume_hits < 2:
        return False, "This document doesn't contain enough resume-like content (work experience, education, personal details, etc.)."

    return True, None


# ==================================================
# HOME
# ==================================================
@app.route("/")
def home():
    return "InterviewAce Backend Running"


# ==================================================
# REGISTER
# ==================================================
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    users = load_json(USERS_FILE)
    for user in users:
        if user["email"] == email:
            return jsonify({"message": "User already exists"}), 400

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users.append({"name": name, "email": email, "password": hashed})
    save_json(USERS_FILE, users)
    return jsonify({"message": "Registered Successfully"})


# ==================================================
# LOGIN
# ==================================================
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    users = load_json(USERS_FILE)
    for user in users:
        if user["email"] == email:
            if bcrypt.checkpw(password.encode(), user["password"].encode()):
                return jsonify({"message": "Login Success", "name": user["name"]})

    return jsonify({"message": "Invalid Credentials"}), 401


# ==================================================
# UPLOAD RESUME
# ==================================================
@app.route("/upload-resume", methods=["POST"])
def upload_resume():
    try:
        if "file" not in request.files:
            return jsonify({"message": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"message": "No selected file"}), 400

        filename = file.filename.lower()
        text = ""

        if filename.endswith(".pdf"):
            pdf = pdfplumber.open(file)
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

        elif filename.endswith(".docx"):
            doc = Document(io.BytesIO(file.read()))
            for para in doc.paragraphs:
                text += para.text + "\n"

        elif filename.endswith(".txt"):
            text = file.read().decode("utf-8")

        else:
            return jsonify({"message": "Only PDF, DOCX, TXT supported"}), 400

        # ── Validate it's actually a resume ──
        valid, reason = is_resume(text)
        if not valid:
            return jsonify({
                "message": f"⚠️ Invalid document: {reason} Please upload a valid resume."
            }), 400

        return jsonify({"text": text})

    except Exception as e:
        return jsonify({"message": str(e)}), 500


# ==================================================
# RESUME ANALYZER
# ==================================================
@app.route("/analyze-resume", methods=["POST"])
def analyze_resume():
    data = request.json
    text = data.get("text", "")
    role = data.get("role", "Software Engineer")

    if not text.strip():
        return jsonify({"message": "Resume text required"}), 400

    # ── Validate pasted text too ──
    valid, reason = is_resume(text)
    if not valid:
        return jsonify({
            "message": f"⚠️ Invalid document: {reason} Please paste a valid resume."
        }), 400

    text_lower = text.lower()

    role_skills = {
        "Software Engineer": ["python", "java", "sql", "git", "docker", "api"],
        "Data Analyst":      ["python", "sql", "excel", "tableau", "power bi", "analytics"],
        "Frontend Developer":["react", "javascript", "html", "css", "ui", "responsive"],
        "Java Developer":    ["java", "spring", "hibernate", "mysql", "oop", "api"]
    }

    target = role_skills.get(role, [])
    found = [s.title() for s in target if s in text_lower]
    missing = [s.title() for s in target if s not in text_lower]

    score = 50 + (len(found) * 8)
    if "project" in text_lower:    score += 10
    if "experience" in text_lower or "internship" in text_lower: score += 10
    if "summary" in text_lower:    score += 5
    if "@" in text:                score += 5
    score = min(score, 100)

    ats = max(score - 5, 0)

    suggestions = []
    if len(found) < 3:            suggestions.append("Add more role-specific skills")
    if "project" not in text_lower:    suggestions.append("Mention at least one project")
    if "experience" not in text_lower: suggestions.append("Add an experience section")
    if "summary" not in text_lower:    suggestions.append("Add a professional summary")

    aiReview = "AI review unavailable."
    aiSummary = "No summary generated."

    try:
        prompt = f"""
You are a premium resume reviewer.

Target Role: {role}

Resume:
{text[:4000]}

Give concise professional feedback.

Return EXACTLY:

Review: short paragraph
Summary: one strong professional summary
"""
        result = ask_ollama(prompt)

        review_match = re.search(r"Review:\s*(.*)", result, re.IGNORECASE)
        summary_match = re.search(r"Summary:\s*(.*)", result, re.IGNORECASE)

        if review_match:  aiReview = review_match.group(1).strip()
        if summary_match: aiSummary = summary_match.group(1).strip()

    except:
        pass

    return jsonify({
        "score": score,
        "atsScore": ats,
        "skillsFound": found,
        "missingSkills": missing,
        "suggestions": suggestions,
        "aiReview": aiReview,
        "aiSummary": aiSummary
    })


# ==================================================
# END-OF-INTERVIEW FEEDBACK
# ==================================================
@app.route("/interview-feedback", methods=["POST"])
def interview_feedback():
    data = request.json
    name = data.get("name", "Guest")
    role = data.get("role", "General")

    history = load_json(HISTORY_FILE)
    user_history = [x for x in history if x["name"] == name and x["role"] == role]
    recent = user_history[-3:] if len(user_history) >= 3 else user_history

    if not recent:
        return jsonify({"feedback": "No session data found.", "avgScore": 0})

    avg_score = round(sum(int(x["score"]) for x in recent) / len(recent))

    qa_text = "\n".join([
        f"Q: {x['question']}\nA: {x['answer']}\nScore: {x['score']}/100"
        for x in recent
    ])

    try:
        prompt = f"""
You are a friendly career coach giving quick post-interview feedback.

Candidate's answers:
{qa_text}

Average Score: {avg_score}/100

Give exactly 4-5 short bullet points. Each point should be ONE sentence, casual and human.
Cover: overall vibe, 1-2 strengths, 1-2 things to improve, and one closing encouragement.

Format EXACTLY like this (use • as bullet, no bold, no headers):
• [point 1]
• [point 2]
• [point 3]
• [point 4]
• [point 5]

Keep each point under 20 words. Sound like a real person, not a robot.
"""
        result = ask_ollama(prompt)
        result = re.sub(r'^(feedback|summary|review):\s*', '', result.strip(), flags=re.IGNORECASE)
        return jsonify({"feedback": result, "avgScore": avg_score})
    except:
        return jsonify({
            "feedback": f"You finished the {role} interview with an average score of {avg_score}/100. Great effort — keep practicing!",
            "avgScore": avg_score
        })


# ==================================================
# MANUAL INTERVIEW SCORE
# ==================================================
def manual_score(answer):
    a = answer.lower().strip()
    words = a.split()

    rude_words = ["shut up", "idiot", "stupid", "boring"]
    weak_words = ["idk", "nothing", "lol", "lmao", "whatever", "skip", "ok", "k"]

    # Rude — terminate immediately
    if any(word in a for word in rude_words):
        return 1, "Unprofessional response."

    # Pure one-word junk
    if a in weak_words or len(a) <= 2:
        return 5, "Weak answer. Please give a proper response."

    # Very short (under 4 words) with no substance
    if len(words) < 4:
        return 15, "Too brief. Please elaborate with more detail."

    # Has some content but could be better (4-9 words)
    if len(words) < 10:
        return 35, "Answer is a bit short. Try to add more details and structure."

    # Decent length — let Ollama score it properly
    return None, None


# ==================================================
# MOCK INTERVIEW
# ==================================================
@app.route("/mock-score", methods=["POST"])
def mock_score():
    data = request.json
    question = data.get("question", "")
    answer   = data.get("answer", "")
    name     = data.get("name", "Guest")
    role     = data.get("role", "General")

    quick_score, quick_feedback = manual_score(answer)

    if quick_score is not None:
        score    = quick_score
        feedback = quick_feedback
    else:
        try:
            prompt = f"""
You are a friendly but honest interviewer evaluating a candidate's response.

Question asked: {question}
Candidate's answer: {answer}

Score their answer out of 100 based on relevance, clarity, and depth.
Then give ONE short, conversational sentence of feedback — like a real interviewer would say it.

Return EXACTLY:
Score: <number>
Feedback: <one sentence>
"""
            result = ask_ollama(prompt)
            score_match = re.search(r'(\d+)', result)
            score = int(score_match.group(1)) if score_match else 50
            score = max(1, min(score, 100))

            feedback_match = re.search(r'Feedback:\s*(.*)', result, re.IGNORECASE)
            feedback = feedback_match.group(1).strip() if feedback_match else "Improve answer clarity."

        except:
            score    = 50
            feedback = "AI unavailable."

    history = load_json(HISTORY_FILE)
    history.append({
        "name": name, "role": role,
        "question": question, "answer": answer,
        "score": score, "feedback": feedback,
        "date": datetime.now().strftime("%d-%m-%Y %H:%M")
    })
    save_json(HISTORY_FILE, history)

    return jsonify({"score": score, "feedback": feedback})


# ==================================================
# DASHBOARD
# ==================================================
@app.route("/dashboard-stats/<name>", methods=["GET"])
def dashboard(name):
    history = load_json(HISTORY_FILE)
    rows = [item for item in history if item["name"] == name]
    total = len(rows)

    if total == 0:
        return jsonify({"attempts": 0, "average": 0, "latest": 0, "growth": 0})

    scores = [int(x["score"]) for x in rows]
    return jsonify({
        "attempts": total,
        "average":  round(sum(scores) / total),
        "latest":   scores[-1],
        "growth":   scores[-1] - scores[0] if total > 1 else 0
    })


# ==================================================
# HISTORY
# ==================================================
@app.route("/history/<name>", methods=["GET"])
def history_page(name):
    history = load_json(HISTORY_FILE)
    result = [item for item in reversed(history) if item["name"] == name]
    return jsonify(result)


# ==================================================
# RUN
# ==================================================
if __name__ == "__main__":
    app.run(debug=True, port=5001)