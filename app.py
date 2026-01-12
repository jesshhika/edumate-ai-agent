import os
import re
from datetime import datetime, date
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, send_from_directory
)
import mysql.connector
import bcrypt
import PyPDF2

# === Google Gemini ===
import google.generativeai as genai

# Configure Gemini with your API key
GEMINI_API_KEY = "AIzaSyAKg3V-I0YdS6WyY394yziS2h6o4CrYlr8"
genai.configure(api_key=GEMINI_API_KEY)

# === CONFIG ===
DB_CONFIG = {
    "user": "root",
    "password": "Sesshhika4321*",
    "host": "127.0.0.1",
    "database": "sem"
}

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = "supersecretkey123"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# === DB helper ===
def get_conn():
    return mysql.connector.connect(**DB_CONFIG)

# === Helpers ===
def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrap

def valid_email(email):
    return bool(re.match(r"[^@ ]+@[^@ ]+\.[^@ ]+", email))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf'

# === Gemini AI call ===
def ask_gemini(prompt):
    """
    Call Google Gemini and return its text response.
    """
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception:
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(prompt)
            return response.text
        except Exception:
            try:
                model = genai.GenerativeModel('gemini-flash-latest')
                response = model.generate_content(prompt)
                return response.text
            except Exception as e:
                return f"Error calling Gemini: {e}. Please check your API key and model availability."

def list_available_models():
    try:
        models = genai.list_models()
        available_models = []
        for model in models:
            if 'generateContent' in model.supported_generation_methods:
                available_models.append(model.name)
        return available_models
    except Exception as e:
        return f"Error listing models: {e}"

# === Context processor ===
@app.context_processor
def inject_now():
    return {"now": datetime.utcnow()}

# === Routes ===
@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("home.html")

# ---------------- Register ----------------
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not (name and email and password):
            flash("All fields are required.", "danger")
            return redirect(url_for("register"))

        if not valid_email(email):
            flash("Invalid email format.", "danger")
            return redirect(url_for("register"))

        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            flash("Email already registered. Please login.", "warning")
            cur.close(); conn.close()
            return redirect(url_for("login"))

        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cur.execute("INSERT INTO users (name, email, password_hash) VALUES (%s,%s,%s)",
                    (name, email, hashed))
        conn.commit()
        cur.close(); conn.close()
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

# ---------------- Login ----------------
@app.route("/login", methods=["GET","POST"])
def login():
    if "user_id" in session:
        flash("Already logged in.", "info")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close(); conn.close()
        if user and bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            flash("Login successful.", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html")

# ---------------- Logout ----------------
@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("home"))

# ---------------- Dashboard ----------------
@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    today_plan = None
    plans = []
    progress = []
    today_summary = None

    try:
        cur.execute("DESCRIBE plans")
        plan_columns = [row[0] for row in cur.fetchall()]
        has_user_id = 'user_id' in plan_columns
        has_created_at = 'created_at' in plan_columns

        today_str = date.today().strftime('%Y-%m-%d')
        if has_user_id and has_created_at:
            cur.execute("SELECT plan_text FROM plans WHERE user_id=%s AND date=%s ORDER BY created_at DESC LIMIT 1",
                        (session["user_id"], today_str))
        elif has_user_id:
            cur.execute("SELECT plan_text FROM plans WHERE user_id=%s AND date=%s ORDER BY id DESC LIMIT 1",
                        (session["user_id"], today_str))
        else:
            cur.execute("SELECT plan_text FROM plans WHERE date=%s ORDER BY id DESC LIMIT 1", (today_str,))
        today_plan = cur.fetchone()

        if has_user_id and has_created_at:
            cur.execute("SELECT date, plan_text FROM plans WHERE user_id=%s ORDER BY created_at DESC LIMIT 7",
                        (session["user_id"],))
        elif has_user_id:
            cur.execute("SELECT date, plan_text FROM plans WHERE user_id=%s ORDER BY id DESC LIMIT 7",
                        (session["user_id"],))
        else:
            cur.execute("SELECT date, plan_text FROM plans ORDER BY id DESC LIMIT 7")
        plans = cur.fetchall()

    except Exception as e:
        print(f"Plans query error: {e}")

    try:
        cur.execute("DESCRIBE progress")
        progress_columns = [row[0] for row in cur.fetchall()]
        progress_has_user_id = 'user_id' in progress_columns

        if progress_has_user_id:
            cur.execute("SELECT subject, progress_percent FROM progress WHERE user_id=%s", (session["user_id"],))
        else:
            cur.execute("SELECT subject, progress_percent FROM progress")
        progress = cur.fetchall()
    except Exception as e:
        print(f"Progress query error: {e}")

    if today_plan and today_plan['plan_text']:
        try:
            summary_prompt = f"Summarize this study plan for today in 2-3 sentences:\n{today_plan['plan_text'][:1000]}"
            today_summary = ask_gemini(summary_prompt)
        except Exception as e:
            print(f"Summary generation error: {e}")

    cur.close()
    conn.close()

    return render_template("dashboard.html",
                           plans=plans,
                           progress=progress,
                           today=date.today(),
                           today_plan=today_plan,
                           today_summary=today_summary)

# ---------------- Planner ----------------
@app.route("/planner", methods=["GET", "POST"])
@login_required
def planner():
    if request.method == "POST":
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        topic = request.form.get("plan_text", "").strip()
        use_ai = request.form.get("use_ai")

        if not (start_date and end_date and topic):
            flash("Start date, end date, and topic are required.", "danger")
            return redirect(url_for("planner"))

        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        num_days = (end_dt - start_dt).days + 1

        if use_ai:
            prompt = f"""Create a detailed {num_days}-day study plan for: {topic}
Start Date: {start_date}
End Date: {end_date}

Format the plan as:
Day 1 (Date): [Specific topics and activities]
Day 2 (Date): [Specific topics and activities]
...and so on for all {num_days} days.

Use HTML formatting for bold text (<b>text</b>) and line breaks (<br>). Make it practical and achievable."""
            plan_text = ask_gemini(prompt)
            
            # Convert markdown to HTML
            import re
            plan_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', plan_text)  # **text** to <b>text</b>
            plan_text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', plan_text)      # *text* to <i>text</i>
            plan_text = re.sub(r'\n', '<br>', plan_text)                   # newlines to <br>
        else:
            plan_text = f"{topic} - {num_days} day plan from {start_date} to {end_date}"

        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("DESCRIBE plans")
            columns = [row[0] for row in cur.fetchall()]
            has_user_id = 'user_id' in columns
        except:
            has_user_id = False

        if has_user_id:
            cur.execute("INSERT INTO plans (user_id, date, plan_text) VALUES (%s,%s,%s)",
                        (session["user_id"], start_date, plan_text))
        else:
            cur.execute("INSERT INTO plans (date, plan_text) VALUES (%s,%s)",
                        (start_date, plan_text))
        conn.commit()
        cur.close(); conn.close()
        flash("Study plan saved.", "success")
        return redirect(url_for("planner"))

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("DESCRIBE plans")
        columns = [row[0] for row in cur.fetchall()]
        has_user_id = 'user_id' in columns
    except:
        has_user_id = False

    if has_user_id:
        cur.execute("SELECT * FROM plans WHERE user_id=%s ORDER BY date DESC", (session["user_id"],))
    else:
        cur.execute("SELECT * FROM plans ORDER BY date DESC")
    plans = cur.fetchall()
    cur.close(); conn.close()
    return render_template("planner.html", plans=plans)

# ---------------- Notes Upload & PDF ----------------
@app.route("/notes", methods=["GET","POST"])
@login_required
def notes():
    summary = None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        uploaded_file = request.files.get("pdf_file")
        
        if not title:
            flash("Title is required.", "danger")
            return redirect(url_for("notes"))
        
        # Handle PDF upload
        pdf_filename = None
        if uploaded_file and uploaded_file.filename and allowed_file(uploaded_file.filename):
            pdf_filename = f"{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], pdf_filename)
            uploaded_file.save(file_path)
            
            # Extract text from PDF
            try:
                with open(file_path, 'rb') as file:
                    pdf_reader = PyPDF2.PdfReader(file)
                    pdf_text = ""
                    for page in pdf_reader.pages:
                        pdf_text += page.extract_text() + "\n"
                    content = pdf_text.strip()
            except Exception as e:
                print(f"PDF extraction error: {e}")
        
        if not content:
            flash("Please provide content or upload a PDF file.", "danger")
            return redirect(url_for("notes"))
        
        # Generate summary using AI
        try:
            summary_prompt = f"Summarize this content in 2-3 sentences:\n{content[:1000]}"
            summary = ask_gemini(summary_prompt)
        except Exception as e:
            print(f"Summary generation error: {e}")
        
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO notes (user_id, title, content, source_pdf, created_at) VALUES (%s,%s,%s,%s,%s)",
                    (session["user_id"], title, content, pdf_filename, datetime.now()))
        note_id = cur.lastrowid
        
        # Generate flashcards from the content
        try:
            flashcard_prompt = f"""Create 3-5 flashcards from this content. Format each as:
Q: [Question]
A: [Answer]

Content: {content[:2000]}

Make questions that test understanding, not just memorization."""
            
            flashcard_text = ask_gemini(flashcard_prompt)
            
            # Parse flashcards and save to database
            import re
            flashcard_pairs = re.findall(r'Q:\s*(.*?)\s*A:\s*(.*?)(?=Q:|$)', flashcard_text, re.DOTALL)
            
            for question, answer in flashcard_pairs:
                if question.strip() and answer.strip():
                    cur.execute("INSERT INTO flashcards (note_id, question, answer) VALUES (%s,%s,%s)",
                                (note_id, question.strip(), answer.strip()))
            
        except Exception as e:
            print(f"Flashcard generation error: {e}")
        
        conn.commit(); cur.close(); conn.close()
        flash("Note saved successfully with flashcards generated!", "success")
        return redirect(url_for("notes"))

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM notes WHERE user_id=%s ORDER BY created_at DESC", (session["user_id"],))
    notes_list = cur.fetchall()
    cur.close(); conn.close()
    return render_template("notes.html", notes=notes_list, summary=summary)

@app.route("/uploads/<filename>")
@login_required
def download_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ---------------- Tutor ----------------
@app.route("/tutor", methods=["GET","POST"])
@login_required
def tutor():
    answer = None
    question = None
    chats = []
    
    if request.method == "POST":
        question = request.form.get("query", "").strip()  # Fixed: use 'query' to match template
        if question:
            try:
                answer = ask_gemini(f"Answer this student question concisely and helpfully. Use HTML formatting for bold text (<b>text</b>) and line breaks (<br>): {question}")
                
                # Convert markdown to HTML
                import re
                answer = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', answer)  # **text** to <b>text</b>
                answer = re.sub(r'\*(.*?)\*', r'<i>\1</i>', answer)      # *text* to <i>text</i>
                answer = re.sub(r'\n', '<br>', answer)                   # newlines to <br>
                
                # Save chat to database
                conn = get_conn()
                cur = conn.cursor()
                try:
                    cur.execute("INSERT INTO tutor_chats (user_id, question, answer, created_at) VALUES (%s,%s,%s,%s)",
                                (session["user_id"], question, answer, datetime.now()))
                    conn.commit()
                except Exception as e:
                    print(f"Chat save error: {e}")
                    # Table might not exist, continue without saving
                cur.close(); conn.close()
                
            except Exception as e:
                print(f"Gemini API error: {e}")
                answer = f"Sorry, I'm having trouble connecting to the AI service. Error: {str(e)}"
    
    # Get chat history
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT question, answer, created_at FROM tutor_chats WHERE user_id=%s ORDER BY created_at ASC", (session["user_id"],))
        chats = cur.fetchall()
    except Exception as e:
        print(f"Chat history error: {e}")
        # Table might not exist yet
    cur.close(); conn.close()
    
    return render_template("tutor.html", answer=answer, question=question, chats=chats)

# ---------------- Assignments ----------------
@app.route("/assignments", methods=["GET", "POST"])
@login_required
def assignments():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        due_date = request.form.get("due_date")
        use_ai = request.form.get("use_ai")
        
        if not title:
            flash("Title is required.", "danger")
            return redirect(url_for("assignments"))
        
        if use_ai and description:
            # Generate assignment using AI
            prompt = f"Create a detailed assignment for: {title}\nDescription: {description}\nDue date: {due_date or 'No specific due date'}\n\nMake it comprehensive and educational. Use HTML formatting for bold text (<b>text</b>) and line breaks (<br>)."
            description = ask_gemini(prompt)
            
            # Convert markdown to HTML
            import re
            description = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', description)  # **text** to <b>text</b>
            description = re.sub(r'\*(.*?)\*', r'<i>\1</i>', description)      # *text* to <i>text</i>
            description = re.sub(r'\n', '<br>', description)                   # newlines to <br>
        
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO assignments (user_id, title, description, due_date, status) VALUES (%s,%s,%s,%s,%s)",
                    (session["user_id"], title, description, due_date, "pending"))
        conn.commit()
        cur.close(); conn.close()
        flash("Assignment added successfully.", "success")
        return redirect(url_for("assignments"))
    
    # Handle toggle status
    toggle_id = request.args.get("toggle")
    if toggle_id:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT status FROM assignments WHERE id=%s AND user_id=%s", (toggle_id, session["user_id"]))
        assignment = cur.fetchone()
        if assignment:
            current_status = assignment[0]
            new_status = "completed" if current_status == "pending" else "pending"
            cur.execute("UPDATE assignments SET status=%s WHERE id=%s", (new_status, toggle_id))
            conn.commit()
        cur.close(); conn.close()
        return redirect(url_for("assignments"))
    
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM assignments WHERE user_id=%s ORDER BY due_date ASC", (session["user_id"],))
    assignments_list = cur.fetchall()
    cur.close(); conn.close()
    return render_template("assignments.html", items=assignments_list)

# ---------------- View Assignment ----------------
@app.route("/assignment/<int:assignment_id>")
@login_required
def view_assignment(assignment_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM assignments WHERE id=%s AND user_id=%s", (assignment_id, session["user_id"]))
    assignment = cur.fetchone()
    cur.close(); conn.close()
    
    if not assignment:
        flash("Assignment not found.", "danger")
        return redirect(url_for("assignments"))
    
    return render_template("assignment_detail.html", assignment=assignment)

# ---------------- View Plan ----------------
@app.route("/plan/<int:plan_id>")
@login_required
def view_plan(plan_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("DESCRIBE plans")
        columns = [row[0] for row in cur.fetchall()]
        has_user_id = 'user_id' in columns
    except:
        has_user_id = False
    
    if has_user_id:
        cur.execute("SELECT * FROM plans WHERE id=%s AND user_id=%s", (plan_id, session["user_id"]))
    else:
        cur.execute("SELECT * FROM plans WHERE id=%s", (plan_id,))
    plan = cur.fetchone()
    cur.close(); conn.close()
    
    if not plan:
        flash("Plan not found.", "danger")
        return redirect(url_for("planner"))
    
    return render_template("plan_detail.html", plan=plan)

# ---------------- View Note ----------------
@app.route("/note/<int:note_id>")
@login_required
def view_note(note_id):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM notes WHERE id=%s AND user_id=%s", (note_id, session["user_id"]))
    note = cur.fetchone()
    
    # Get flashcards for this note if they exist
    flashcards = []
    try:
        cur.execute("SELECT question, answer FROM flashcards WHERE note_id=%s", (note_id,))
        flashcards = cur.fetchall()
    except:
        pass  # Table might not exist yet
    
    cur.close(); conn.close()
    
    if not note:
        flash("Note not found.", "danger")
        return redirect(url_for("notes"))
    
    return render_template("note_detail.html", note=note, flashcards=flashcards)

# ---------------- Uploaded File ----------------
@app.route("/uploads/<filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ---------------- Analytics ----------------
@app.route("/analytics")
@login_required
def analytics():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    
    # Get progress data
    cur.execute("SELECT subject, progress_percent FROM progress WHERE user_id=%s", (session["user_id"],))
    progress_data = cur.fetchall()
    
    # Get assignment statistics
    cur.execute("SELECT COUNT(*) as total, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed FROM assignments WHERE user_id=%s", (session["user_id"],))
    assignment_stats = cur.fetchone()
    
    # Get plans statistics
    cur.execute("SELECT COUNT(*) as total FROM plans WHERE user_id=%s", (session["user_id"],))
    plans_stats = cur.fetchone()
    
    # Get notes statistics
    cur.execute("SELECT COUNT(*) as notes_count FROM notes WHERE user_id=%s", (session["user_id"],))
    notes_stats = cur.fetchone()
    
    # Get flashcards statistics
    cur.execute("SELECT COUNT(*) as flashcards_count FROM flashcards f JOIN notes n ON f.note_id = n.id WHERE n.user_id = %s", (session["user_id"],))
    flashcards_stats = cur.fetchone()
    
    cur.close(); conn.close()
    return render_template("analytics.html", progress_data=progress_data, assignment_stats=assignment_stats, plans_stats=plans_stats, notes_stats=notes_stats, flashcards_stats=flashcards_stats)

# ---------------- Flashcards ----------------
@app.route("/flashcards")
@login_required
def flashcards():
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    
    # Get flashcards from notes
    cards = []
    try:
        cur.execute("SELECT n.title, f.question, f.answer FROM flashcards f JOIN notes n ON f.note_id = n.id WHERE n.user_id = %s", (session["user_id"],))
        cards = cur.fetchall()
    except:
        # If flashcards table doesn't exist, create some sample cards
        cards = [
            {"title": "Sample Study", "question": "What is machine learning?", "answer": "Machine learning is a subset of artificial intelligence that enables computers to learn and make decisions from data without being explicitly programmed."},
            {"title": "Sample Study", "question": "What is the difference between supervised and unsupervised learning?", "answer": "Supervised learning uses labeled data to train models, while unsupervised learning finds patterns in data without labels."},
            {"title": "Sample Study", "question": "What is overfitting in machine learning?", "answer": "Overfitting occurs when a model learns the training data too well, including noise and outliers, making it perform poorly on new data."}
        ]
    
    cur.close(); conn.close()
    return render_template("flashcards.html", cards=cards)

# ---------------- Motivation ----------------
@app.route("/motivation")
@login_required
def motivation():
    prompt = request.args.get("prompt", "Give me a motivational study quote")
    motivation_text = None
    
    if prompt:
        try:
            motivation_text = ask_gemini(f"Provide motivational content for: {prompt}")
        except Exception as e:
            print(f"Motivation generation error: {e}")
            motivation_text = "Keep studying! Every expert was once a beginner. You've got this! 💪"
    
    return render_template("motivation.html", motivation_text=motivation_text)

# ---------------- Recommendations ----------------
@app.route("/recommendations")
@login_required
def recommendations():
    # Get user's recent activity for personalized recommendations
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    
    # Get recent plans
    try:
        cur.execute("SELECT plan_text FROM plans WHERE user_id=%s ORDER BY created_at DESC LIMIT 3", (session["user_id"],))
        recent_plans = cur.fetchall()
    except:
        recent_plans = []
    
    # Get recent notes
    try:
        cur.execute("SELECT title FROM notes WHERE user_id=%s ORDER BY created_at DESC LIMIT 3", (session["user_id"],))
        recent_notes = cur.fetchall()
    except:
        recent_notes = []
    
    cur.close(); conn.close()
    
    # Generate recommendations based on activity
    recommendations_text = None
    try:
        activity_context = ""
        if recent_plans:
            activity_context += f"Recent study plans: {', '.join([p['plan_text'][:100] for p in recent_plans])}\n"
        if recent_notes:
            activity_context += f"Recent notes: {', '.join([n['title'] for n in recent_notes])}\n"
        
        prompt = f"Based on this student's recent activity, provide 3-5 personalized study recommendations:\n{activity_context}"
        recommendations_text = ask_gemini(prompt)
    except Exception as e:
        print(f"Recommendations generation error: {e}")
        recommendations_text = "• Review your recent notes regularly\n• Create a consistent study schedule\n• Take breaks every 45-60 minutes\n• Practice active recall techniques\n• Set specific, achievable goals"
    
    return render_template("recommendations.html", recommendations_text=recommendations_text)

# ---------------- Profile ----------------
@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        if not (name and email and valid_email(email)):
            flash("Valid name and email required.", "danger")
            return redirect(url_for("profile"))
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET name=%s, email=%s WHERE id=%s", (name, email, session["user_id"]))
        conn.commit(); cur.close(); conn.close()
        session["user_name"] = name
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))

    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],))
    user_data = cur.fetchone()
    cur.close(); conn.close()
    return render_template("profile.html", user=user_data)

# ---------------- Run ----------------
if __name__ == "__main__":
    app.run(debug=True)
