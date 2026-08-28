"""
JanSamadhan AI - Grievance Redressal System
SIH26043 - Jharkhand Government
Features: Complaint + File Upload + Admin Login + AI Severity + Duplicate Detection
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from functools import wraps
from werkzeug.utils import secure_filename
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = "jansamadhan_secret_key"

DB_NAME = "complaints.db"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "doc", "docx"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ============================
# AI SEVERITY KEYWORDS
# ============================
CRITICAL_KEYWORDS = [
    "death", "murder", "rape", "accident", "fire", "emergency", "hospital",
    "violence", "flood", "earthquake", "drought", "kidnap", "theft", "robbery",
    "kill", "injured", "blood", "dead", "dying", "urgent", "life threat",
    "suicide", "bomb", "blast", "short circuit", "electric shock", "poison"
]

HIGH_KEYWORDS = [
    "water", "electricity", "road", "broken", "damage", "danger", "fallen",
    "leakage", "sewage", "health", "disease", "mosquito", "garbage", "pollution",
    "noise", "illegal", "corruption", "bribe", "fraud", "cheat", "scam"
]


def detect_severity(title, description):
    """AI-based severity detection using keyword analysis."""
    text = (title + " " + description).lower()
    
    critical_score = sum(1 for word in CRITICAL_KEYWORDS if word in text)
    high_score = sum(1 for word in HIGH_KEYWORDS if word in text)
    
    if critical_score >= 1:
        return "Critical"
    elif high_score >= 2 or critical_score > 0:
        return "High"
    elif high_score == 1:
        return "Medium"
    else:
        return "Low"


def calculate_similarity(text1, text2):
    """Jaccard similarity for duplicate detection."""
    if not text1 or not text2:
        return 0.0
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    if not words1 or not words2:
        return 0.0
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union)


# ============================
# DATABASE SETUP
# ============================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT NOT NULL,
            file_name TEXT,
            status TEXT DEFAULT 'Pending',
            severity TEXT DEFAULT 'Low',
            created_at TEXT
        )
    """)
    
    # Auto-migrate old databases
    for col in ["file_name", "severity"]:
        try:
            cursor.execute(f"ALTER TABLE complaints ADD COLUMN {col} TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    
    cursor.execute("INSERT OR IGNORE INTO admin_users (id, username, password) VALUES (1, 'admin', 'admin123')")
    conn.commit()
    conn.close()


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


init_db()


# ============================
# HELPERS
# ============================
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_logged_in" not in session:
            flash("Kripya pehle login karein!", "error")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


# ============================
# ROUTES
# ============================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/submit", methods=["POST"])
def submit_complaint():
    try:
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        
        # File handling
        file = request.files.get("complaint_file")
        file_name = None
        
        if file and file.filename and file.filename.strip() != "":
            if allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                unique_filename = f"{timestamp}_{filename}"
                full_path = os.path.join(app.config["UPLOAD_FOLDER"], unique_filename)
                file.save(full_path)
                file_name = unique_filename
                print(f"✅ File saved: {full_path}")
            else:
                flash("Sirf image (png, jpg, jpeg, gif) ya document (pdf, doc, docx) files allowed hain!", "error")
                return redirect(url_for("home"))

        # Validation
        if not name or not title or not description or not location:
            flash("Kripya sabhi zaroori fields bharein!", "error")
            return redirect(url_for("home"))

        # AI Severity Detection
        severity = detect_severity(title, description)
        
        # Auto-set Critical status
        status = "Critical" if severity == "Critical" else "Pending"

        conn = get_db_connection()
        conn.execute(
            """INSERT INTO complaints 
               (name, contact, title, description, location, file_name, status, severity, created_at) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, contact, title, description, location, file_name, status, severity,
             datetime.now().strftime("%d-%m-%Y %H:%M"))
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        sev_msg = f" | Severity: {severity}" if severity in ["Critical", "High"] else ""
        flash(f"Complaint submit ho gayi! ID: {new_id}{sev_msg}", "success")
        return redirect(url_for("home"))
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for("home"))


@app.route("/track", methods=["GET", "POST"])
def track_complaint():
    complaint = None
    if request.method == "POST":
        complaint_id = request.form.get("complaint_id", "").strip()
        if complaint_id:
            conn = get_db_connection()
            complaint = conn.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
            conn.close()
            if complaint is None:
                flash("Is ID ki koi complaint nahi mili.", "error")
    return render_template("track.html", complaint=complaint)


# ============================
# ADMIN ROUTES
# ============================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        conn = get_db_connection()
        admin = conn.execute(
            "SELECT * FROM admin_users WHERE username = ? AND password = ?", 
            (username, password)
        ).fetchone()
        conn.close()
        if admin:
            session["admin_logged_in"] = True
            session["admin_username"] = admin["username"]
            flash("Admin login safal!", "success")
            return redirect(url_for("admin"))
        else:
            flash("Galat username ya password!", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)
    flash("Logout ho gaye!", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin():
    conn = get_db_connection()
    complaints = conn.execute("SELECT * FROM complaints ORDER BY id DESC").fetchall()
    conn.close()
    
    # Duplicate detection logic
    complaint_list = [dict(c) for c in complaints]
    duplicates = {}
    
    for i, c1 in enumerate(complaint_list):
        dup_ids = []
        for j, c2 in enumerate(complaint_list):
            if i != j and c1["id"] != c2["id"]:
                text1 = c1["title"] + " " + c1["description"] + " " + c1["location"]
                text2 = c2["title"] + " " + c2["description"] + " " + c2["location"]
                sim = calculate_similarity(text1, text2)
                if sim > 0.5:  # 50% similarity = duplicate
                    dup_ids.append({"id": c2["id"], "sim": round(sim*100)})
        if dup_ids:
            duplicates[c1["id"]] = dup_ids
    
    return render_template("admin.html", complaints=complaints, duplicates=duplicates)


@app.route("/update_status/<int:complaint_id>", methods=["POST"])
@login_required
def update_status(complaint_id):
    new_status = request.form.get("status")
    conn = get_db_connection()
    conn.execute("UPDATE complaints SET status = ? WHERE id = ?", (new_status, complaint_id))
    conn.commit()
    conn.close()
    flash("Status update ho gaya!", "success")
    return redirect(url_for("admin"))


@app.route("/delete/<int:complaint_id>")
@login_required
def delete_complaint(complaint_id):
    """Resolved complaint delete karne ka option."""
    conn = get_db_connection()
    
    # Pehle complaint ka status check karo
    complaint = conn.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
    
    if complaint is None:
        conn.close()
        flash("Complaint nahi mili!", "error")
        return redirect(url_for("admin"))
    
    # Sirf Resolved ya Critical resolved wali delete ho sakti hai
    if complaint["status"] in ["Resolved", "Critical"]:
        # File bhi delete karo agar hai
        if complaint["file_name"]:
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], complaint["file_name"])
            if os.path.exists(file_path):
                os.remove(file_path)
        
        conn.execute("DELETE FROM complaints WHERE id = ?", (complaint_id,))
        conn.commit()
        conn.close()
        flash(f"Complaint #{complaint_id} delete ho gayi!", "success")
    else:
        conn.close()
        flash("Sirf Resolved complaints hi delete ho sakti hain!", "error")
    
    return redirect(url_for("admin"))


# ============================
# FILE SERVING
# ============================
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # Serve uploaded complaint images/documents from static/uploads
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)