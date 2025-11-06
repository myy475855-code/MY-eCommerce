import os
import uuid
from datetime import datetime , timedelta
from pathlib import Path
from werkzeug.utils import secure_filename
from time import sleep
import random
from flask import (
    Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, current_app
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user, UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from dotenv import load_dotenv
import smtplib
from email.message import EmailMessage

# Load .env if present
load_dotenv()

# --- Config ---
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")

app.config["SECRET_KEY"] = os.environ.get("MYSHOP_SECRET", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR/'myshop.db'}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["UPLOAD_PATH"] = "static/uploads"
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB default per request

# Mail config (optional)
app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT") or 587)
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "True") == "True"
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", "no-reply@myshop.local")

# --- Extensions ---
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])

# --- Models ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    country = db.Column(db.String(100))
    province = db.Column(db.String(100))
    city = db.Column(db.String(100))
    address = db.Column(db.Text)
    zip_code = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    orders = db.relationship("Order", backref="user", lazy=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    specifications = db.Column(db.Text)
    categories = db.Column(db.String(500))  # comma-separated categories
    price = db.Column(db.Float, default=0.0)
    main_image = db.Column(db.String(500))  # e.g. /static/uploads/uuid.jpg
    image2 = db.Column(db.String(500))
    image3 = db.Column(db.String(500))
    image4 = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    product = db.relationship("Product", backref="cart_items", lazy=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(100), unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    total_amount = db.Column(db.Float, default=0.0)
    shipping = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(50), default="Pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship("OrderItem", backref="order", lazy=True)


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    product_name = db.Column(db.String(255))
    unit_price = db.Column(db.Float)
    quantity = db.Column(db.Integer, default=1)
    
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    name = db.Column(db.String(120))
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- Login loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Helpers ---
def send_email(subject: str, recipient: str, body_text: str):
    server = app.config.get("MAIL_SERVER")
    if not server:
        print("----- EMAIL (console) -----")
        print("To:", recipient)
        print("Subject:", subject)
        print(body_text)
        print("---------------------------")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = app.config.get("MAIL_DEFAULT_SENDER")
    msg["To"] = recipient
    msg.set_content(body_text)

    try:
        if app.config.get("MAIL_USE_TLS"):
            smtp = smtplib.SMTP(server, app.config.get("MAIL_PORT"))
            smtp.starttls()
        else:
            smtp = smtplib.SMTP_SSL(server, app.config.get("MAIL_PORT"))
        smtp.login(app.config.get("MAIL_USERNAME"), app.config.get("MAIL_PASSWORD"))
        smtp.send_message(msg)
        smtp.quit()
    except Exception as e:
        print("Failed to send email:", e)
        print(body_text)

def save_uploaded_file(fs):
    if not fs:
        return None
    filename = fs.filename
    if filename == "":
        return None
    _, ext = os.path.splitext(filename)
    unique_name = f"{uuid.uuid4().hex}{ext}"
    dest = Path(app.config["UPLOAD_FOLDER"]) / unique_name
    fs.save(dest)
    rel = os.path.relpath(dest, Path(app.root_path) / "static")
    return f"/static/{rel.replace(os.path.sep, '/')}"

def generate_order_number():
    return f"ORD-{uuid.uuid4().hex[:10].upper()}"

def _get_cart():
    return session.setdefault("cart", {})

# --- Routes ---
@app.route("/")
def index():
    products = Product.query.order_by(Product.created_at.desc()).limit(12).all()
    return render_template("index.html", products=products)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        if not email:
            flash("Email is required", "danger")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("Email already registered", "warning")
            return redirect(url_for("register"))

        user = User(
            email=email,
            first_name=request.form["firstName"],
            last_name=request.form["lastName"],
            phone=request.form["phone"],
            country=request.form["country"],
            province=request.form["province"],
            city=request.form["city"],
            address=request.form["address"],
            zip_code=request.form["zip"],
        )
        password = request.form.get("password") or request.form.get("pwd") or "changeme"
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Registered. Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form["email"] or "").strip().lower()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for("index"))
        flash("Invalid credentials", "danger")
        return redirect(url_for("login"))
    return render_template("signin.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out", "info")
    return redirect(url_for("index"))

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current_user.first_name = request.form["firstName"]
        current_user.last_name = request.form["lastName"]
        current_user.phone = request.form["phone"]
        db.session.commit()
        flash("Profile updated", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=current_user)

@app.route("/profile/change-location", methods=["POST"])
@login_required
def change_location():
    current_user.country = request.form["country"]
    current_user.province = request.form["province"]
    current_user.city = request.form["city"]
    current_user.zip_code = request.form["zip_code"]
    current_user.address = request.form["address"]
    db.session.commit()
    flash("Location updated", "success")
    return redirect(url_for("profile"))

@app.route("/upload-product", methods=["GET", "POST"])
def upload_product():
    if request.method == "POST":
        # 1. Get form data safely
        name = request.form.get("product_name", "")
        desc = request.form.get("description", "")
        specs = request.form.get("specifications", "")
        categories = request.form.getlist("categories")
        if not categories:
            categories = [request.form.get("productCategory", "")]
        categories = ",".join([c for c in categories if c])

        try:
            price = float(request.form.get("price", 0.0))
        except ValueError:
            price = 0.0

        # 2. Process uploaded images
        uploaded_files = []
        for key in ["image1", "image2", "image3", "image4"]:
            file = request.files.get(key)
            if file and file.filename != "":
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config["UPLOAD_PATH"], filename)
                file.save(filepath)
                uploaded_files.append(filename)
            else:
                uploaded_files.append(None)

        # 3. Create product instance
        p = Product(
            name=name,
            description=desc,
            specifications=specs,
            categories=categories,
            price=price,
            main_image=uploaded_files[0],
            image2=uploaded_files[1],
            image3=uploaded_files[2],
            image4=uploaded_files[3],
        )

        # 4. Save to database
        db.session.add(p)
        db.session.commit()

        flash("✅ Product uploaded successfully!", "success")
        return redirect(url_for("upload_product"))

    # 5. Render upload page
    return render_template("upload.html")

@app.route("/products")
def products():
    page = int(request.args.get("page", 1))
    per = 12
    q = Product.query.order_by(Product.created_at.desc())
    pag = q.paginate(page=page, per_page=per, error_out=False)
    return render_template("products.html", pagination=pag)

@app.route("/product/<int:product_id>", methods=["GET", "POST"])
def product_detail(product_id):
    p = Product.query.get_or_404(product_id)
    if request.method == "POST":
        body = request.form["comment"]
        if not body:
            flash("Comment can not be empty", "warning")
            return redirect(request.url)
        c = Comment(
            product_id=p.id,
            user_id=current_user.get_id() if current_user.is_authenticated else None,
            name=(current_user.first_name if current_user.is_authenticated else request.form["name"] or "Guest"),
            body=body
        )
        db.session.add(c)
        db.session.commit()
        flash("Comment posted", "success")
        return redirect(request.url)

    images = [p.main_image] + [img for img in (p.image2, p.image3, p.image4) if img]
    comments = Comment.query.filter_by(product_id=p.id).order_by(Comment.created_at.desc()).all()
    return render_template("index.html", product=p, images=images, comments=comments)

@app.route("/cart/add/<int:product_id>", methods=["POST"])
@login_required
def cart_add(product_id):
    qty = int(request.form.get("quantity", 1))
    item = Cart.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if item:
        item.quantity += qty
    else:
        item = Cart(user_id=current_user.id, product_id=product_id, quantity=qty)
        db.session.add(item)
    db.session.commit()
    flash("Product added to your cart!", "success")
    return redirect(request.referrer or url_for("cart"))


@app.route("/cart")
@login_required
def cart():
    cart_items = Cart.query.filter_by(user_id=current_user.id).all()
    total = sum((item.product.price if item.product else 0) * item.quantity for item in cart_items)
    return render_template("cart.html", items=cart_items, total=total)

@app.route("/cart/remove/<int:item_id>")
@login_required
def cart_remove(item_id):
    item = Cart.query.filter_by(item_id=item_id, user_id=current_user.id).first_or_404()
    if item:
        db.session.delete(item)
        db.session.commit()
        flash("Item removed from your cart.", "info")
    return redirect(url_for("cart"))

@app.route("/cart/update", methods=["POST"])
def cart_update():
    cart = {}
    for key, val in request.form.items():
        if key.startswith("qty_"):
            pid = key.split("_", 1)[1]
            try:
                q = int(val)
                if q > 0:
                    cart[pid] = q
            except:
                pass
    session["cart"] = cart
    flash("Cart updated", "success")
    return redirect(url_for("cart"))

@app.route("/cart/confirm", methods=["GET", "POST"])
@login_required
def cart_confirm():
    """
    Shows order confirmation page before final checkout.
    Displays user info, shipping address, cart items, and payment options.
    """
    cart_items = Cart.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        flash("Your cart is empty!", "warning")
        return redirect(url_for("cart"))

    total = sum((item.product.price or 0) * item.quantity for item in cart_items)

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        if payment_method not in ["card", "cod"]:
            flash("Please select a payment method.", "danger")
            return redirect(url_for("cart_confirm"))

        # Temporarily store payment method in session
        session["payment_method"] = payment_method
        flash("Payment method selected.", "info")
        return redirect(url_for("cart_checkout"))

    return render_template(
        "confirm_order.html",
        user=current_user,
        items=cart_items,
        total=total
    )


@app.route("/cart/checkout", methods=["GET", "POST"])
@login_required
def cart_checkout():
    """
    Final checkout — creates the order after the user confirms details and payment method.
    """
    cart_items = Cart.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        flash("Your cart is empty!", "warning")
        return redirect(url_for("cart"))

    payment_method = session.pop("payment_method", None)
    if not payment_method:
        flash("Please confirm your order first.", "warning")
        return redirect(url_for("cart_confirm"))

    total = sum((item.product.price or 0) * item.quantity for item in cart_items)

    # Create new order
    order = Order(
        order_number=generate_order_number(),
        user_id=current_user.id,
        total_amount=total,
        shipping=0.0,
        status="Processing" if payment_method == "cod" else "Awaiting Payment",
    )
    db.session.add(order)
    db.session.commit()

    # Add order items
    for item in cart_items:
        order_item = OrderItem(
            order_id=order.id,
            product_id=item.product.id,
            user_id=current_user.id,
            product_name=item.product.name,
            unit_price=item.product.price,
            quantity=item.quantity,
        )
        db.session.add(order_item)
        db.session.delete(item)  # Clear from cart after ordering
    db.session.commit()

    # Payment handling
    if payment_method == "cod":
        flash("✅ Order placed successfully! You will pay upon delivery.", "success")
        return redirect(url_for("order_confirmation", order_id=order.id))

    elif payment_method == "card":
        # Simulate successful card payment for now
        order.status = "Paid"
        db.session.commit()
        flash("✅ Payment successful! Your order has been placed.", "success")
        return redirect(url_for("order_confirmation", order_id=order.id))

    flash("Unexpected error occurred during checkout.", "danger")
    return redirect(url_for("cart"))

@app.route("/order/<int:order_id>/confirmation")
@login_required
def order_confirmation(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template("order.html", order=order)

@app.route("/orders")
@login_required
def orders():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template("order.html", orders=orders)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"]
        user = User.query.filter_by(email=email).first()

        if user:
            # Generate a 6-digit verification code
            code = str(random.randint(100000, 999999))

            # Store the code and its expiry (10 min) in session (or database)
            session["reset_email"] = email
            session["reset_code"] = code
            session["reset_expiry"] = (datetime.utcnow() + timedelta(minutes=10)).isoformat()

            # Send code via email
            body = f"""Your password reset code is: {code}

            This code will expire in 10 minutes.
            If you did not request this, please ignore this email."""
            send_email("MyShop Password Reset Code", user.email, body)

        flash("If an account exists, a verification code has been sent to your email.", "info")
        return redirect(url_for("verify_code"))

    return render_template("forgot_password.html")


@app.route("/verify-code", methods=["GET", "POST"])
def verify_code():
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        saved_code = session.get("reset_code")
        expiry_str = session.get("reset_expiry")

        if not saved_code or not expiry_str:
            flash("No code found. Please request a new one.", "danger")
            return redirect(url_for("forgot_password"))

        expiry = datetime.fromisoformat(expiry_str)
        if datetime.utcnow() > expiry:
            flash("Your verification code has expired. Please request a new one.", "danger")
            return redirect(url_for("forgot_password"))

        if code != saved_code:
            flash("Invalid verification code. Please try again.", "warning")
            return redirect(url_for("verify_code"))

        # Code is valid — allow password reset
        flash("Code verified. Please set a new password.", "success")
        return redirect(url_for("reset_password"))

    return render_template("verify_code.html")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    email = session.get("reset_email")
    if not email:
        flash("Session expired. Please restart the password reset process.", "danger")
        return redirect(url_for("forgot_password"))

    user = User.query.filter_by(email=email).first_or_404()

    if request.method == "POST":
        new = request.form["newPassword"]
        confirm = request.form["confirmPassword"]

        if not new or new != confirm:
            flash("Passwords do not match.", "warning")
            return redirect(request.url)

        user.set_password(new)
        db.session.commit()

        # Clear session
        session.pop("reset_email", None)
        session.pop("reset_code", None)
        session.pop("reset_expiry", None)

        flash("Your password has been reset successfully. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", user=user)

@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    products = []

    if query:
        products = Product.query.filter(
            (Product.name.ilike(f"%{query}%")) |
            (Product.description.ilike(f"%{query}%")) |
            (Product.categories.ilike(f"%{query}%"))
        ).all()

    return render_template("search_results.html", query=query, products=products)

@app.route("/contact", methods=["POST"])
def contact():
    email = request.form["email"]
    message = request.form["message"]

    if not email or not message:
        flash("Please enter both email and message.", "warning")
        return redirect(request.referrer or url_for("index"))

    body = f"""
    New contact form submission from MyShop:

    From: {email}
    Message:
    {message}
    """

    send_email("New Contact Message - MyShop", "myy502388@gmail.com", body)
    flash("Your message has been sent successfully. We'll contact you soon!", "success")
    return redirect(request.referrer or url_for("index"))

@app.cli.command("init-db")
def init_db_command():
    db.create_all()
    print("✅ Database initialized successfully.")

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return render_template("500.html"), 500

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
