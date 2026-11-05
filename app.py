import os
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import (
    Flask, abort, flash, redirect, render_template, request,
    session, url_for
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-this")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///farm_market.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="buyer")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    price = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    location = db.Column(db.String(120), nullable=False, default="")
    farmer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    farmer = db.relationship("User", backref="products")


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Placed")
    total = db.Column(db.Numeric(10, 2), nullable=False)
    buyer = db.relationship("User", backref="orders")
    items = db.relationship(
        "OrderItem", backref="order", cascade="all, delete-orphan"
    )


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    product_name = db.Column(db.String(120), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    product = db.relationship("Product")


def current_user():
    user_id = session.get("user_id")
    return db.session.get(User, user_id) if user_id else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user().role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.context_processor
def add_user_to_templates():
    return {"current_user": current_user()}


@app.get("/")
def home():
    search = request.args.get("q", "").strip()
    query = Product.query.filter(Product.quantity > 0)
    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(
                Product.name.ilike(like),
                Product.category.ilike(like),
                Product.location.ilike(like),
            )
        )
    return render_template("home.html", products=query.order_by(Product.name).all())


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "buyer")

        if not name or "@" not in email or len(password) < 8:
            flash("Enter a name, valid email, and password of at least 8 characters.", "error")
        elif role not in {"buyer", "farmer"}:
            flash("Invalid account type.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(
                name=name,
                email=email,
                password_hash=generate_password_hash(password),
                role=role,
            )
            db.session.add(user)
            db.session.commit()
            session["user_id"] = user.id
            flash("Account created. Welcome!", "success")
            return redirect(url_for("home"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.id
            return redirect(url_for("home"))

        flash("Email or password is incorrect.", "error")

    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/farmer/products/new", methods=["GET", "POST"])
@role_required("farmer")
def new_product():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()

        try:
            price = Decimal(request.form.get("price", ""))
            quantity = int(request.form.get("quantity", ""))
            if price <= 0 or quantity < 0:
                raise ValueError()
        except (InvalidOperation, ValueError):
            flash("Price must be positive and quantity must be zero or more.", "error")
            return render_template("product.html")

        if not name or not category:
            flash("Product name and category are required.", "error")
            return render_template("product.html")

        product = Product(
            name=name, category=category, location=location,
            description=description, price=price, quantity=quantity,
            farmer_id=current_user().id,
        )
        db.session.add(product)
        db.session.commit()
        flash("Produce listing added.", "success")
        return redirect(url_for("home"))

    return render_template("product.html")


@app.post("/farmer/products/<int:product_id>/delete")
@role_required("farmer")
def delete_product(product_id):
    product = db.get_or_404(Product, product_id)
    if product.farmer_id != current_user().id:
        abort(403)
    db.session.delete(product)
    db.session.commit()
    flash("Listing deleted.", "success")
    return redirect(url_for("home"))


@app.get("/cart")
@role_required("buyer")
def cart():
    cart_data = session.get("cart", {})
    items = []
    total = Decimal("0.00")

    for product_id, quantity in cart_data.items():
        product = db.session.get(Product, int(product_id))
        if product and int(quantity) > 0:
            subtotal = product.price * int(quantity)
            items.append({"product": product, "quantity": int(quantity), "subtotal": subtotal})
            total += subtotal

    return render_template("cart.html", items=items, total=total)


@app.post("/cart/add/<int:product_id>")
@role_required("buyer")
def add_to_cart(product_id):
    product = db.get_or_404(Product, product_id)
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 0

    if quantity < 1 or quantity > product.quantity:
        flash("Choose a quantity within the available stock.", "error")
    else:
        cart_data = session.get("cart", {})
        new_quantity = int(cart_data.get(str(product_id), 0)) + quantity
        if new_quantity > product.quantity:
            flash("Your cart would exceed available stock.", "error")
        else:
            cart_data[str(product_id)] = new_quantity
            session["cart"] = cart_data
            flash("Added to cart.", "success")

    return redirect(url_for("home"))


@app.post("/checkout")
@role_required("buyer")
def checkout():
    cart_data = session.get("cart", {})
    if not cart_data:
        flash("Your cart is empty.", "error")
        return redirect(url_for("cart"))

    try:
        order = Order(buyer_id=current_user().id, total=Decimal("0.00"))
        total = Decimal("0.00")

        # Lock rows where supported and recheck stock before reducing it.
        for product_id, quantity in cart_data.items():
            product = db.session.get(Product, int(product_id))
            quantity = int(quantity)
            if not product or quantity < 1 or quantity > product.quantity:
                raise ValueError("Some items no longer have enough stock.")

            subtotal = product.price * quantity
            total += subtotal
            product.quantity -= quantity
            order.items.append(OrderItem(
                product_id=product.id,
                product_name=product.name,
                quantity=quantity,
                unit_price=product.price,
            ))

        order.total = total
        db.session.add(order)
        db.session.commit()
        session.pop("cart", None)
        flash(f"Order #{order.id} placed successfully.", "success")
        return redirect(url_for("dashboard"))

    except (ValueError, TypeError):
        db.session.rollback()
        flash("Some items no longer have enough stock. Please review your cart.", "error")
        return redirect(url_for("cart"))


@app.get("/dashboard")
@login_required
def dashboard():
    user = current_user()
    if user.role == "buyer":
        orders = Order.query.filter_by(buyer_id=user.id).order_by(Order.id.desc()).all()
    elif user.role == "farmer":
        product_ids = [p.id for p in user.products]
        orders = (
            Order.query.join(OrderItem)
            .filter(OrderItem.product_id.in_(product_ids))
            .order_by(Order.id.desc()).all()
            if product_ids else []
        )
    else:
        orders = Order.query.order_by(Order.id.desc()).all()
    return render_template("dashboard.html", orders=orders)


@app.post("/admin/orders/<int:order_id>/status")
@role_required("admin")
def update_order_status(order_id):
    order = db.get_or_404(Order, order_id)
    status = request.form.get("status", "")
    allowed = {"Placed", "Confirmed", "Dispatched", "Delivered"}
    if status not in allowed:
        abort(400)
    order.status = status
    db.session.commit()
    flash("Order status updated.", "success")
    return redirect(url_for("dashboard"))


with app.app_context():
    db.create_all()

    # Demo products appear on a fresh database.
    if Product.query.count() == 0:
        farmer = User.query.filter_by(email="farmer@example.com").first()
        if not farmer:
            farmer = User(
                name="Demo Farmer",
                email="farmer@example.com",
                password_hash=generate_password_hash("Farmer123!"),
                role="farmer",
            )
            db.session.add(farmer)
            db.session.flush()

        db.session.add_all([
            Product(
                name="Fresh Tomatoes", category="Vegetables",
                description="Ripe tomatoes, freshly harvested.",
                price=Decimal("80.00"), quantity=30,
                location="Kiambu", farmer_id=farmer.id,
            ),
            Product(
                name="Sweet Bananas", category="Fruits",
                description="Sweet, locally grown bananas.",
                price=Decimal("120.00"), quantity=24,
                location="Murang'a", farmer_id=farmer.id,
            ),
        ])
        db.session.commit()


if __name__ == "__main__":
    app.run(debug=True)