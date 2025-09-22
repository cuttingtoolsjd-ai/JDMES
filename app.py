from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from sqlalchemy import func
import qrcode
from PIL import Image, ImageDraw, ImageFont
import os

app = Flask(__name__)
app.secret_key = "secret123"

# Database setup
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///mes.db"
db = SQLAlchemy(app)

# ========================
# Database Models
# ========================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    pin = db.Column(db.String(6), default="000000")
    role = db.Column(db.String(20))  # operator, manager, master
    must_change_pin = db.Column(db.Boolean, default=True)


class WorkOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    work_order_no = db.Column(db.String(50), unique=True, nullable=False)
    client_name = db.Column(db.String(100))
    po_number = db.Column(db.String(100))
    part_name = db.Column(db.String(100))
    quantity = db.Column(db.Integer, nullable=False)
    completed_qty = db.Column(db.Integer, default=0)
    rejected_qty = db.Column(db.Integer, default=0)
    diameter = db.Column(db.Float)
    flute_length = db.Column(db.Float)
    overall_length = db.Column(db.Float)
    due_date = db.Column(db.String(20))
    status = db.Column(db.String(20), default="Not Started")

    # Operator tracking
    current_operator = db.Column(db.String(50))
    previous_operator = db.Column(db.String(50))
    current_machine = db.Column(db.String(50))
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    last_handover_time = db.Column(db.DateTime)
    # Add complaint field for order logs and complaints
    complaint = db.Column(db.String(200))


class RejectionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_order.id"))
    operator = db.Column(db.String(50))
    quantity = db.Column(db.Integer)
    reason = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# ========================
# QR Code Generator
# ========================
QR_FOLDER = os.path.join("static", "qrcodes")
os.makedirs(QR_FOLDER, exist_ok=True)

def generate_qr_with_text(order_no):
    qr = qrcode.make(order_no).convert("RGB")

    width, height = qr.size
    new_height = height + 40
    img_with_text = Image.new("RGB", (width, new_height), "white")
    img_with_text.paste(qr, (0, 0))

    draw = ImageDraw.Draw(img_with_text)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), order_no, font=font)
    text_width = bbox[2] - bbox[0]
    text_x = (width - text_width) // 2

    draw.text((text_x, height + 10), order_no, fill="black", font=font)

    filepath = os.path.join(QR_FOLDER, f"{order_no}.png")
    img_with_text.save(filepath)
    return filepath


# ========================
# Helper Functions
# ========================
def get_operator_stats(username):
    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday())

    daily_completed = db.session.query(func.sum(WorkOrder.completed_qty)).filter(
        WorkOrder.current_operator == username,
        func.date(WorkOrder.end_time) == today
    ).scalar() or 0

    daily_rejected = db.session.query(func.sum(WorkOrder.rejected_qty)).filter(
        WorkOrder.current_operator == username,
        func.date(WorkOrder.end_time) == today
    ).scalar() or 0

    weekly_completed = db.session.query(func.sum(WorkOrder.completed_qty)).filter(
        WorkOrder.current_operator == username,
        func.date(WorkOrder.end_time) >= week_start
    ).scalar() or 0

    weekly_rejected = db.session.query(func.sum(WorkOrder.rejected_qty)).filter(
        WorkOrder.current_operator == username,
        func.date(WorkOrder.end_time) >= week_start
    ).scalar() or 0

    return {
        "daily_completed": daily_completed,
        "daily_rejected": daily_rejected,
        "weekly_completed": weekly_completed,
        "weekly_rejected": weekly_rejected,
    }


# ========================
# Routes
# ========================
@app.route("/")
def home():
    return redirect(url_for("login"))


# ---------- LOGIN ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        pin = request.form.get("pin", "").strip()

        if not pin.isdigit() or len(pin) != 6:
            return render_template("login.html", message="PIN must be exactly 6 digits.")

        user = User.query.filter_by(username=username, pin=pin).first()

        if user:
            session["username"] = user.username
            session["role"] = user.role
            if user.must_change_pin:
                return redirect(url_for("set_pin"))
            if user.role == "master":
                return redirect(url_for("manager_dashboard", username=user.username))
            elif user.role == "manager":
                return redirect(url_for("manager_dashboard", username=user.username))
            else:
                return redirect(url_for("operator_dashboard", username=user.username))
        else:
            return render_template("login.html", message="Invalid username or PIN")

    return render_template("login.html")


@app.route("/set_pin", methods=["GET", "POST"])
def set_pin():
    if "username" not in session:
        return redirect(url_for("login"))

    message = ""
    if request.method == "POST":
        new_pin = request.form.get("pin", "").strip()

        if new_pin and new_pin.isdigit() and len(new_pin) == 6:
            user = User.query.filter_by(username=session["username"]).first()
            if user:
                user.pin = new_pin
                user.must_change_pin = False
                db.session.commit()
                return redirect(url_for("login"))
        else:
            message = "PIN must be exactly 6 digits and numeric!"

    return render_template("set_pin.html", message=message)


# ---------- MANAGER / MASTER ----------
@app.route("/create_order", methods=["GET", "POST"])
def create_order():
    qr_path = None
    message = ""
    if request.method == "POST":
        work_order_no = request.form["work_order_no"]

        existing_order = WorkOrder.query.filter_by(work_order_no=work_order_no).first()
        if existing_order:
            message = f"⚠️ Work Order {work_order_no} already exists!"
            return render_template("create_order.html", message=message)

        order = WorkOrder(
            work_order_no=work_order_no,
            client_name=request.form["client_name"],
            po_number=request.form["po_number"],
            part_name=request.form["part_name"],
            quantity=int(request.form["quantity"]),
            diameter=float(request.form["diameter"]),
            flute_length=float(request.form["flute_length"]),
            overall_length=float(request.form["overall_length"]),
            due_date=request.form["due_date"],
            status="Not Started"
        )
        db.session.add(order)
        db.session.commit()

        filepath = generate_qr_with_text(order.work_order_no)
        qr_path = f"/{filepath}"
        message = f"✅ Work Order {order.work_order_no} created successfully!"

    return render_template("create_order.html", message=message, qr_path=qr_path)


@app.route("/qrcodes")
def view_qrcodes():
    files = os.listdir(QR_FOLDER)
    qr_files = [f for f in files if f.endswith(".png")]
    return render_template("qrcodes.html", qr_files=qr_files)


@app.route("/workorders")
def view_workorders():
    orders = WorkOrder.query.all()
    return render_template("workorders.html", orders=orders)


@app.route("/search_workorders")
def search_workorders():
    query = request.args.get("q", "").strip()
    results = []
    if query:
        results = WorkOrder.query.filter(
            (WorkOrder.work_order_no.contains(query)) |
            (WorkOrder.client_name.contains(query)) |
            (WorkOrder.po_number.contains(query)) |
            (WorkOrder.current_operator.contains(query))
        ).all()
    return render_template("search_results.html", results=results, query=query)


@app.route("/manager_dashboard/<username>")
def manager_dashboard(username):
    if "username" not in session or session["username"] != username:
        return redirect(url_for("login"))

    # Get all work orders
    all_orders = WorkOrder.query.all()

    # For active ones (not completed yet)
    active_orders = WorkOrder.query.filter(WorkOrder.status != "Completed").all()

    # Stats by employee
    employee_stats = db.session.query(
        WorkOrder.current_operator,
        func.sum(WorkOrder.completed_qty).label("completed"),
        func.sum(WorkOrder.rejected_qty).label("rejected")
    ).group_by(WorkOrder.current_operator).all()

    # Stats by dimensions
    dimension_stats = db.session.query(
        WorkOrder.diameter,
        WorkOrder.flute_length,
        WorkOrder.overall_length,
        func.sum(WorkOrder.completed_qty).label("completed"),
        func.sum(WorkOrder.rejected_qty).label("rejected")
    ).group_by(WorkOrder.diameter, WorkOrder.flute_length, WorkOrder.overall_length).all()

    return render_template(
        "manager_dashboard.html",
        username=username,
        active_orders=active_orders,
        all_orders=all_orders,
        employee_stats=employee_stats,
        dimension_stats=dimension_stats,
        operator_efficiency=get_operator_efficiency
    )
    


# ---------- OPERATOR ----------
@app.route("/scan", methods=["GET", "POST"])
def scan_order():
    message = ""
    order = None
    if request.method == "POST":
        work_order_no = request.form["work_order_no"]
        username = request.form["username"]
        machine = request.form["machine"]

        order = WorkOrder.query.filter_by(work_order_no=work_order_no).first()
        if not order:
            message = f"❌ Work Order {work_order_no} not found!"
            return render_template("scan.html", message=message, order=None)
        else:
            # Handover logic: if order is Waiting for Handover, mark as Completed and assign to new operator
            if order.status == "Waiting for Handover":
                order.previous_operator = order.current_operator
                order.current_operator = username
                order.current_machine = machine
                order.status = "Completed"
                order.end_time = datetime.utcnow()
                db.session.commit()
                message = f"✅ Work Order {work_order_no} handover complete. Marked as Completed and assigned to {username}."
                return render_template("scan.html", message=message, order=order)
            elif order.status == "Completed":
                message = f"✅ Work Order {work_order_no} already completed."
                return render_template("scan.html", message=message, order=order)
            else:
                order.previous_operator = order.current_operator
                order.current_operator = username
                order.current_machine = machine
                order.status = "In Progress"

                if not order.start_time:
                    order.start_time = datetime.utcnow()
                else:
                    order.last_handover_time = datetime.utcnow()

                db.session.commit()
                # Redirect directly to finish_order page for this work order
                return redirect(url_for('finish_order', order_no=work_order_no))

    return render_template("scan.html", message=message, order=order)  

def get_operator_efficiency():
    operators = User.query.filter(User.role == "operator").all()
    efficiency_data = []
    today = datetime.utcnow().date()
    for op in operators:
        # All time
        completed = WorkOrder.query.filter_by(current_operator=op.username, status="Completed").count()
        partial = WorkOrder.query.filter_by(current_operator=op.username, status="Partial").count()
        rejections = RejectionLog.query.filter_by(operator=op.username).all()
        rejected_qty = sum([r.quantity for r in rejections])
        total_orders = WorkOrder.query.filter_by(current_operator=op.username).count()
        total_qty = sum([wo.quantity for wo in WorkOrder.query.filter_by(current_operator=op.username).all()])
        completion_rate = (completed / total_orders * 100) if total_orders else 0
        rejection_rate = (rejected_qty / total_qty * 100) if total_qty else 0
        # Placeholder for time efficiency and overall score
        time_efficiency = 100
        overall_score = (completion_rate + (100 - rejection_rate) + time_efficiency) / 3

        # Daily completed and rejected
        daily_completed = db.session.query(func.sum(WorkOrder.completed_qty)).filter(
            WorkOrder.current_operator == op.username,
            WorkOrder.status == "Completed",
            func.date(WorkOrder.end_time) == today
        ).scalar() or 0

        daily_rejected = db.session.query(func.sum(RejectionLog.quantity)).filter(
            RejectionLog.operator == op.username,
            func.date(RejectionLog.timestamp) == today
        ).scalar() or 0

        efficiency_data.append({
            "operator": op.username,
            "completed": completed,
            "partial": partial,
            "rejected_qty": rejected_qty,
            "completion_rate": round(completion_rate, 1),
            "rejection_rate": round(rejection_rate, 1),
            "time_efficiency": time_efficiency,
            "overall_score": round(overall_score, 1),
            "daily_completed": daily_completed,
            "daily_rejected": daily_rejected
        })
    return efficiency_data


@app.route("/finish_order/<order_no>", methods=["GET", "POST"])
def finish_order(order_no):
    if "username" not in session:
        return redirect(url_for("login"))

    order = WorkOrder.query.filter_by(work_order_no=order_no).first()
    if not order:
        return "Order not found", 404

    message = ""
    role = session.get("role", "operator")

    if request.method == "POST":
        try:
            qty = int(request.form.get("quantity", 0))
        except ValueError:
            qty = 0

        action = request.form["action"]
        complaint = request.form.get("complaint", "").strip()

        if qty <= 0 and action != "close_order":
            message = "❌ Quantity must be greater than 0."
        elif order.completed_qty + order.rejected_qty + qty > order.quantity:
            message = f"❌ Cannot exceed total order quantity ({order.quantity})."
        else:
            if complaint:
                order.complaint = complaint

            # --- Operator Actions ---
            if role == "operator":
                if action in ["complete", "partial"]:
                    order.completed_qty += qty
                    order.status = "Waiting for Handover"
                    order.end_time = datetime.utcnow()
                    db.session.commit()
                    return redirect(url_for("operator_dashboard", username=session["username"]))

                elif action == "reject":
                    reason = request.form.get("reason", "No reason")
                    order.rejected_qty += qty
                    new_rejection = RejectionLog(
                        work_order_id=order.id,
                        operator=order.current_operator,
                        quantity=qty,
                        reason=reason,
                    )
                    db.session.add(new_rejection)
                    order.status = "Waiting for Handover"
                    order.end_time = datetime.utcnow()

                    # Auto-create rework order
                    from random import randint
                    new_order_no = f"{order.work_order_no}-R{randint(1000,9999)}"
                    new_order = WorkOrder(
                        work_order_no=new_order_no,
                        client_name=order.client_name,
                        po_number=order.po_number,
                        part_name=order.part_name,
                        quantity=qty,
                        diameter=order.diameter,
                        flute_length=order.flute_length,
                        overall_length=order.overall_length,
                        due_date=order.due_date,
                        status="Not Started",
                        complaint=complaint or None,
                    )
                    db.session.add(new_order)
                    db.session.commit()
                    generate_qr_with_text(new_order_no)

                    return redirect(url_for("operator_dashboard", username=session["username"]))

                else:
                    message = "⚠️ Operators cannot fully close work orders."

            # --- Manager Actions ---
            elif role == "manager" or role == "master":
                if action == "close_order":
                    order.status = "Completed"
                    order.end_time = datetime.utcnow()
                    db.session.commit()
                    message = f"✅ Work Order {order.work_order_no} fully closed by manager."
                    return redirect(url_for("manager_dashboard", username=session["username"]))

                elif action in ["complete", "partial", "reject"]:
                    # Managers can still act like operators if needed
                    return redirect(url_for("finish_order", order_no=order_no))

    # --- Build Action Logs ---
    logs = []
    rejections = RejectionLog.query.filter_by(work_order_id=order.id).order_by(RejectionLog.timestamp).all()
    for rej in rejections:
        logs.append({
            "timestamp": rej.timestamp.strftime("%Y-%m-%d %H:%M"),
            "operator": rej.operator,
            "action": "Rejected",
            "quantity": rej.quantity,
            "reason": rej.reason,
        })
    if order.start_time:
        logs.append({
            "timestamp": order.start_time.strftime("%Y-%m-%d %H:%M"),
            "operator": order.current_operator or "",
            "action": "Started",
            "quantity": "",
            "reason": "",
        })
    if order.last_handover_time:
        logs.append({
            "timestamp": order.last_handover_time.strftime("%Y-%m-%d %H:%M"),
            "operator": order.current_operator or "",
            "action": "Handed Over",
            "quantity": "",
            "reason": getattr(order, "complaint", "") or "",
        })
    if order.end_time:
        logs.append({
            "timestamp": order.end_time.strftime("%Y-%m-%d %H:%M"),
            "operator": order.current_operator or "",
            "action": order.status,
            "quantity": order.completed_qty,
            "reason": getattr(order, "complaint", "") or "",
        })
    logs = sorted(logs, key=lambda x: x["timestamp"])

    return render_template("finish_order.html", order=order, message=message, logs=logs, role=role)

@app.route("/operator_dashboard/<username>")
def operator_dashboard(username):
    if "username" not in session or session["username"] != username:
        return redirect(url_for("login"))

    # Show both "In Progress" and "Waiting for Handover" as active
    active_orders = WorkOrder.query.filter(
        WorkOrder.current_operator == username,
        WorkOrder.status == "In Progress"
    ).all()
    completed_orders = WorkOrder.query.filter_by(current_operator=username, status="Completed").all()
    rejections = RejectionLog.query.filter_by(operator=username).all()
    stats = get_operator_stats(username)

    return render_template(
        "operator_dashboard.html",
        username=username,
        active_orders=active_orders,
        completed_orders=completed_orders,
        rejections=rejections,
        stats=stats
    )

@app.route('/operator_efficiency')
def operator_efficiency():
    operator_efficiency = get_operator_efficiency()
    return render_template('operator_efficiency.html', operator_efficiency=operator_efficiency)


@app.route("/order_log", methods=["GET", "POST"])
def order_log():
    logs = []
    order = None
    work_order_no = ""
    if request.method == "POST":
        work_order_no = request.form.get("work_order_no", "").strip()
        order = WorkOrder.query.filter_by(work_order_no=work_order_no).first()
        if order:
            # Build the log: assignment, start, handover, completion, rejections
            logs = []
            # Assignment/start
            if order.start_time:
                logs.append({
                    "timestamp": order.start_time.strftime("%Y-%m-%d %H:%M"),
                    "operator": order.current_operator or "",
                    "action": "Started",
                    "quantity": "",
                    "reason": ""
                })
            # Handover
            if order.last_handover_time:
                logs.append({
                    "timestamp": order.last_handover_time.strftime("%Y-%m-%d %H:%M"),
                    "operator": order.current_operator or "",
                    "action": "Handed Over",
                    "quantity": "",
                    "reason": order.complaint or ""
                })
            # Completion
            if order.end_time:
                logs.append({
                    "timestamp": order.end_time.strftime("%Y-%m-%d %H:%M"),
                    "operator": order.current_operator or "",
                    "action": order.status,
                    "quantity": order.completed_qty,
                    "reason": order.complaint or ""
                })
            # Rejections
            rejections = RejectionLog.query.filter_by(work_order_id=order.id).order_by(RejectionLog.timestamp).all()
            for rej in rejections:
                logs.append({
                    "timestamp": rej.timestamp.strftime("%Y-%m-%d %H:%M"),
                    "operator": rej.operator,
                    "action": "Rejected",
                    "quantity": rej.quantity,
                    "reason": rej.reason
                })
            # Sort logs by timestamp
            logs = sorted(logs, key=lambda x: x["timestamp"])
    return render_template("order_log.html", logs=logs, order=order, work_order_no=work_order_no)

# ========================
# Run the App with Preloaded Users
# ========================
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

        # Insert users manually if not exist
        predefined_users = [
            ("Anushwa", "000000", "master"),
            ("Jayant", "000000", "master"),
            ("SUSHIL BABAR", "000000", "operator"),
            ("ANIL PARGAVE", "000000", "operator"),
            ("POOJA CHAVAN", "000000", "operator"),
            ("ANIL ADSULE", "000000", "operator"),
            ("RAMESH KOKATE", "000000", "operator"),
            ("VISHAL KAKADE", "000000", "operator"),
            ("SAGAR GAVDE", "000000", "operator"),
            ("VISHAL MADHAV THORAT", "000000", "operator"),
            ("VIKAS BHAGWAN GADEKAR", "000000", "operator"),
            ("MUKESH BINAY RAJBHAR", "000000", "operator"),
            ("ANIL PAWAR", "000000", "operator"),
            ("SUNIL PAWAR", "000000", "operator"),
            ("SUSHIL GADE", "000000", "operator"),
            ("DNYANESHWAR HIMMAT BAGUL", "000000", "operator"),
            ("AKHADE KISHORKUMAR OMPRAKASH", "000000", "operator"),
            ("AJINKYA PASHEWAD", "000000", "operator"),
            ("VISHAL BIDGAR", "000000", "operator"),
            ("ABHISHEK KARNALE", "000000", "operator"),
            ("LALMANI YADAV", "000000", "operator"),
            ("KRISHNA LAVATE", "000000", "operator"),
            ("NITESH SHARMA", "000000", "operator"),
            ("LAXMAN GADEKAR", "000000", "operator"),
            ("ROHIT RAJBHAR", "000000", "operator"),
            ("SANTOSH MULEY", "000000", "operator"),
            ("SHANKAR BAHIRAT", "000000", "operator"),
            ("GOVIND KHOSE", "000000", "manager"),
            ("PRATIBHA KANADE", "000000", "operator"),
            ("SHITAL SUTAR", "000000", "operator"),
            ("SWATI DEOKAR", "000000", "operator"),
            ("JYOTI KAMBLE", "000000", "operator"),
            ("PRAKASH SINGH SAINI", "000000", "manager"),
            ("TULSIDAS WAGHAMARE", "000000", "manager"),
            ("DHANASHREE JAGTAP", "000000", "manager"),
            ("PALLAVI KUKADE", "000000", "operator"),
            ("NIKKI THAKER", "000000", "operator"),
            ("VINAY KUMAR", "000000", "operator"),
            ("ROHIT KAMBLE", "000000", "manager"),
            ("CHHAT BAI SAHU", "000000", "operator"),
            ("GAJANAN GIRAMKAR", "000000", "operator"),
            ("SUSHILA KARSH", "000000", "operator")
        ]


        for username, pin, role in predefined_users:
            if not User.query.filter_by(username=username).first():
                db.session.add(User(username=username, pin=pin, role=role, must_change_pin=True))

        db.session.commit()

    app.run(debug=True)
    db.session.add(User(username=username, pin=pin, role=role, must_change_pin=True))

    db.session.commit()