from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# User table
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)  # plain for now, later we hash
    role = db.Column(db.String(20), nullable=False)  # Operator, Manager, Master

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
    rejection_reason = db.Column(db.String(200))
    complaint = db.Column(db.String(200))
