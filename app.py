from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from groq import Groq
import json
from datetime import datetime  
from flask_mysqldb import MySQL
from config import Config
from dotenv import load_dotenv
import MySQLdb.cursors
import re
import os


load_dotenv()

# Ensure there are NO spaces inside the quotes
client = Groq(api_key=os.getenv('GROQ_API_KEY'))

# Initialize app
app = Flask(__name__)
app.config.from_object(Config)


# Setup MySQL
mysql = MySQL(app)

# ---------- HELPER FUNCTIONS ----------
def get_categories():
    """Get all categories from database"""
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM categories ORDER BY name")
    return cursor.fetchall()

@app.context_processor
def inject_categories():
    return dict(get_categories=get_categories)


# ---------- ROUTES ----------
@app.route('/')
def home():
    if 'loggedin' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Check against database
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users WHERE username = %s AND password = %s', (username, password))
        account = cursor.fetchone()
        
        if account:
            session['loggedin'] = True
            session['id'] = account['id']
            session['username'] = account['username']
            session['role'] = account['role']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # 1. Total Products Count
    cursor.execute("SELECT COUNT(*) as count FROM products")
    total_products = cursor.fetchone()['count']
    
    # 2. Low Stock Count
    cursor.execute("SELECT COUNT(*) as count FROM products WHERE stock_quantity <= min_stock_level")
    low_stock = cursor.fetchone()['count']
    
    # 3. Today's Sales Revenue
    cursor.execute("SELECT COALESCE(SUM(total_amount), 0) as total FROM sales WHERE DATE(created_at) = CURDATE()")
    today_sales = float(cursor.fetchone()['total'])
    
    # 4. Today's Profit Calculation
    cursor.execute("""
        SELECT COALESCE(SUM((si.unit_price - p.purchase_price) * si.quantity), 0) as profit
        FROM sale_items si
        JOIN products p ON si.product_id = p.id
        JOIN sales s ON si.sale_id = s.id
        WHERE DATE(s.created_at) = CURDATE()
    """)
    today_profit = float(cursor.fetchone()['profit'])
    
    # 5. Top 3 Products Today
    cursor.execute("""
        SELECT p.name, SUM(si.quantity) as total_sold
        FROM sale_items si
        JOIN products p ON si.product_id = p.id
        JOIN sales s ON si.sale_id = s.id
        WHERE DATE(s.created_at) = CURDATE()
        GROUP BY p.id ORDER BY total_sold DESC LIMIT 3
    """)
    top_products = cursor.fetchall()
    
    # 6. Live Alerts (From Products table)
    cursor.execute("""
        SELECT name as product_name, 
        CONCAT('Stock: ', stock_quantity, ' (Min: ', min_stock_level, ')') as message
        FROM products 
        WHERE stock_quantity <= min_stock_level
        LIMIT 5
    """)
    alerts = cursor.fetchall()
    
    return render_template('dashboard.html',
                           username=session['username'],
                           total_products=total_products,
                           low_stock=low_stock,
                           today_sales=today_sales,
                           today_profit=today_profit,
                           top_products=top_products,
                           alerts=alerts)

# ---------- PRODUCT ROUTES ----------
@app.route('/products')
def products():
    if not session.get('loggedin'):
        flash('Please login first', 'error')
        return redirect(url_for('home'))
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Get ALL products from database
    cursor.execute("""
        SELECT p.*, c.name as category_name 
        FROM products p 
        LEFT JOIN categories c ON p.category_id = c.id 
        ORDER BY p.id DESC
    """)
    products_list = cursor.fetchall()
    
    # Get categories from database
    categories = get_categories()
    
    return render_template('products.html', 
                         username=session['username'],
                         products=products_list,
                         categories=categories)

@app.route('/add_product', methods=['POST'])
def add_product():
    if not session.get('loggedin'):
        flash('Please login first', 'error')
        return redirect(url_for('home'))
    
    try:
        # Get form data
        name = request.form.get('name')
        category_id = request.form.get('category_id')
        purchase_price = float(request.form.get('purchase_price', 0))
        selling_price = float(request.form.get('selling_price', 0))
        stock_quantity = int(request.form.get('stock_quantity', 0))
        min_stock_level = int(request.form.get('min_stock_level', 5))
        
        # Save to MySQL database
        description = request.form.get('description', '')
        cursor = mysql.connection.cursor()

        cursor.execute("""
            INSERT INTO products (name, category_id, purchase_price, selling_price, 
                                stock_quantity, min_stock_level, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (name, category_id, purchase_price, selling_price, 
            stock_quantity, min_stock_level, description))
        
        product_id = cursor.lastrowid
        
        # Check if low stock and create alert
        if stock_quantity <= min_stock_level:
            cursor.execute("""
                INSERT INTO alerts (product_id, message)
                VALUES (%s, %s)
            """, (product_id, f'Low stock: {stock_quantity} units (min: {min_stock_level})'))
        
        mysql.connection.commit()
        
        flash(f'✅ Product "{name}" added successfully!', 'success')
        
    except Exception as e:
        mysql.connection.rollback()
        flash(f'❌ Error: {str(e)}', 'error')
    
    return redirect(url_for('products'))

# ---------- STOCK UPDATE ROUTE ----------
@app.route('/update_stock/<int:product_id>', methods=['POST'])
def update_stock(product_id):
    if not session.get('loggedin'):
        return jsonify({'error': 'Please login first'}), 401
    
    try:
        new_stock = int(request.form.get('stock', 0))
        reason = request.form.get('reason', 'Manual Update') # Captured from new JS
        
        # Use DictCursor for easier data handling
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # Get current product info
        cursor.execute("SELECT name, min_stock_level FROM products WHERE id = %s", (product_id,))
        product = cursor.fetchone()
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # 1. Update stock in database
        cursor.execute("UPDATE products SET stock_quantity = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", 
                      (new_stock, product_id))
        
        # OPTIONAL: If you have a stock_history table, you would insert the 'reason' here:
        # cursor.execute("INSERT INTO stock_history (product_id, quantity, reason) VALUES (%s, %s, %s)", (product_id, new_stock, reason))

        # 2. Check if low stock and manage alerts
        if new_stock <= product['min_stock_level']:
            cursor.execute("SELECT id FROM alerts WHERE product_id = %s AND is_resolved = FALSE", (product_id,))
            existing_alert = cursor.fetchone()
            
            alert_msg = f'Low stock: {new_stock} units (min: {product["min_stock_level"]})'
            if existing_alert:
                cursor.execute("UPDATE alerts SET message = %s WHERE id = %s", (alert_msg, existing_alert['id']))
            else:
                cursor.execute("INSERT INTO alerts (product_id, message) VALUES (%s, %s)", (product_id, alert_msg))
        else:
            # Mark alert as resolved if stock is now sufficient
            cursor.execute("UPDATE alerts SET is_resolved = TRUE WHERE product_id = %s", (product_id,))
        
        mysql.connection.commit()
        return jsonify({
            'success': True,
            'message': f'Stock updated to {new_stock}',
            'new_stock': new_stock
        })
    
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 400

# ---------- EDIT PRODUCT ROUTE ----------
@app.route('/edit_product/<int:product_id>', methods=['POST'])
def edit_product(product_id):
    if not session.get('loggedin'):
        return jsonify({'error': 'Please login first'}), 401
    
    try:
        name = request.form.get('name')
        category_id = request.form.get('category_id')
        purchase_price = float(request.form.get('purchase_price', 0))
        selling_price = float(request.form.get('selling_price', 0))
        min_stock_level = int(request.form.get('min_stock_level', 5))
        description = request.form.get('description', '')
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # Get current stock to re-evaluate alert status
        cursor.execute("SELECT stock_quantity FROM products WHERE id = %s", (product_id,))
        product_data = cursor.fetchone()
        if not product_data:
            return jsonify({'error': 'Product not found'}), 404
            
        current_stock = product_data['stock_quantity']
        
        # Update product
        cursor.execute("""
            UPDATE products 
            SET name = %s, category_id = %s, purchase_price = %s, 
                selling_price = %s, min_stock_level = %s, description = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (name, category_id, purchase_price, selling_price, 
              min_stock_level, description, product_id))
        
        # Re-evaluate Alert based on NEW min_stock_level
        if current_stock <= min_stock_level:
            cursor.execute("SELECT id FROM alerts WHERE product_id = %s AND is_resolved = FALSE", (product_id,))
            existing_alert = cursor.fetchone()
            
            alert_msg = f'Low stock: {current_stock} units (min: {min_stock_level})'
            if existing_alert:
                cursor.execute("UPDATE alerts SET message = %s WHERE id = %s", (alert_msg, existing_alert['id']))
            else:
                cursor.execute("INSERT INTO alerts (product_id, message) VALUES (%s, %s)", (product_id, alert_msg))
        else:
            cursor.execute("UPDATE alerts SET is_resolved = TRUE WHERE product_id = %s", (product_id,))
        
        mysql.connection.commit()
        return jsonify({'success': True, 'message': 'Product updated successfully'})
    
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 400

# ---------- DELETE PRODUCT ROUTE ----------
@app.route('/delete_product/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    # Security check
    if not session.get('loggedin') or session.get('role') != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # Get product name
        cursor.execute("SELECT name FROM products WHERE id = %s", (product_id,))
        product = cursor.fetchone()
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        product_name = product['name']
        
        # Check if product has sales records (to prevent database integrity errors)
        cursor.execute("SELECT COUNT(*) as count FROM sale_items WHERE product_id = %s", (product_id,))
        sales_count = cursor.fetchone()['count']
        
        if sales_count > 0:
            return jsonify({
                'success': False,
                'error': f'Cannot delete "{product_name}" because it has {sales_count} sales records. Please mark it as inactive instead.'
            })
        
        # Delete linked alerts first, then the product
        cursor.execute("DELETE FROM alerts WHERE product_id = %s", (product_id,))
        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        
        mysql.connection.commit()
        return jsonify({'success': True, 'message': f'Product "{product_name}" deleted successfully'})
    
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 400

        
# ---------- SALES/POS ROUTES ----------
# ---------- UPDATED POS ROUTE ----------
@app.route('/pos')
def pos():
    if 'loggedin' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Get products with categories
    cursor.execute("""
        SELECT p.*, c.name as category_name 
        FROM products p 
        LEFT JOIN categories c ON p.category_id = c.id 
        WHERE p.stock_quantity > 0 
        ORDER BY p.name
    """)
    products = cursor.fetchall()

    # 🔥 FIX: Convert Decimal prices to float for JavaScript compatibility
    for p in products:
        p['selling_price'] = float(p['selling_price'])
        p['purchase_price'] = float(p['purchase_price'])
    
    # Get next invoice number
    cursor.execute("SELECT COUNT(*) as count FROM sales WHERE DATE(created_at) = CURDATE()")
    today_count = cursor.fetchone()['count']
    next_invoice = f"INV{datetime.now().strftime('%Y%m%d')}{today_count + 1:03d}"
    
    return render_template('pos.html', 
                         username=session['username'],
                         products=products,
                         next_invoice=next_invoice)


# ---------- UPDATED SEARCH API ----------
@app.route('/api/products/search')
def search_products():
    if 'loggedin' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    query = request.args.get('q', '')
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    if query:
        cursor.execute("""
            SELECT p.*, c.name as category_name 
            FROM products p 
            LEFT JOIN categories c ON p.category_id = c.id 
            WHERE (p.name LIKE %s OR p.id = %s) 
            AND p.stock_quantity > 0
            LIMIT 10
        """, (f'%{query}%', query if query.isdigit() else 0))
    else:
        cursor.execute("""
            SELECT p.*, c.name as category_name 
            FROM products p 
            LEFT JOIN categories c ON p.category_id = c.id 
            WHERE p.stock_quantity > 0 
            LIMIT 20
        """)
    
    products = cursor.fetchall()

    # CRITICAL FIX: Convert Decimal to float for JSON
    for p in products:
        p['selling_price'] = float(p['selling_price'])
        p['purchase_price'] = float(p['purchase_price'])

    return jsonify(products)

@app.route('/create_sale', methods=['POST'])
def create_sale():
    if 'loggedin' not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401

    data = request.get_json()
    items = data.get('items')
    total_amount = data.get('total')
    payment_mode = data.get('payment_mode')
    
    # Use the same invoice logic you already have
    import random
    invoice_no = f"INV-{random.randint(100000, 999999)}"

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        # 1. Insert into Sales table
        query_sale = "INSERT INTO sales (invoice_no, total_amount, payment_mode) VALUES (%s, %s, %s)"
        cursor.execute(query_sale, (invoice_no, total_amount, payment_mode))
        sale_id = cursor.lastrowid

        # 2. Process each item
        for item in items:
            # Insert into sale_items
            query_item = """
                INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, subtotal) 
                VALUES (%s, %s, %s, %s, %s)
            """
            subtotal = item['quantity'] * item['price']
            cursor.execute(query_item, (sale_id, item['id'], item['quantity'], item['price'], subtotal))

            # 3. Deduct stock
            query_stock = "UPDATE products SET stock_quantity = stock_quantity - %s WHERE id = %s"
            cursor.execute(query_stock, (item['quantity'], item['id']))

            # 4. 🔥 SMART FEATURE: Check for Low Stock after deduction
            # Fetch updated stock and min_level
            cursor.execute("SELECT name, stock_quantity, min_stock_level FROM products WHERE id = %s", (item['id'],))
            prod = cursor.fetchone()

            if prod and prod['stock_quantity'] <= prod['min_stock_level']:
                # Check if an active alert already exists so we don't spam the database
                cursor.execute("SELECT id FROM alerts WHERE product_id = %s AND is_resolved = FALSE", (item['id'],))
                existing_alert = cursor.fetchone()

                alert_msg = f"Low stock: {prod['stock_quantity']} units remaining (Min: {prod['min_stock_level']})"
                
                if existing_alert:
                    cursor.execute("UPDATE alerts SET message = %s WHERE id = %s", (alert_msg, existing_alert['id']))
                else:
                    cursor.execute("INSERT INTO alerts (product_id, message) VALUES (%s, %s)", (item['id'], alert_msg))

        mysql.connection.commit()
        return jsonify({
            "success": True, 
            "invoice": invoice_no, 
            "sale_id": sale_id
        })
    
    except Exception as e:
        mysql.connection.rollback()
        print(f"Error: {str(e)}") 
        return jsonify({"success": False, "error": str(e)})
        
# ---------- REPORTS ROUTES ----------
# ---------- REPORTS ROUTES ----------
@app.route('/reports')
def reports():
    if 'loggedin' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # 1. Today's sales (Correct as is)
    cursor.execute("""
        SELECT COUNT(*) as transactions,
               COALESCE(SUM(total_amount), 0) as revenue
        FROM sales 
        WHERE DATE(created_at) = CURDATE()
    """)
    today = cursor.fetchone()
    
    # 2. Total products count (Correct as is)
    cursor.execute("SELECT COUNT(*) as total FROM products")
    total_products = cursor.fetchone()['total']
    
    # 3. Low stock products (Correct as is)
    cursor.execute("""
        SELECT p.name, p.stock_quantity, p.min_stock_level, c.name as category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.stock_quantity <= p.min_stock_level
        ORDER BY p.stock_quantity ASC
        LIMIT 10
    """)
    low_stock = cursor.fetchall()
    
    # 4. FIX: Top selling products (Added all selected columns to GROUP BY)
    cursor.execute("""
        SELECT p.name, p.selling_price, p.purchase_price, ANY_VALUE(c.name) as category_name,
               COALESCE(SUM(si.quantity), 0) as total_sold
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN sale_items si ON p.id = si.product_id
        LEFT JOIN sales s ON si.sale_id = s.id AND s.created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        GROUP BY p.id, p.name, p.selling_price, p.purchase_price
        ORDER BY total_sold DESC
        LIMIT 5
    """)
    top_products = cursor.fetchall()

    # 5. FIX: Chart Data (Group by the same formatted string we Select)
    cursor.execute("""
        SELECT DATE_FORMAT(created_at, '%a') as day, SUM(total_amount) as total, DATE(created_at) as sale_date
        FROM sales
        WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
        GROUP BY sale_date, day
        ORDER BY sale_date ASC
    """)
    chart_results = cursor.fetchall()
    chart_labels = [row['day'] for row in chart_results]
    chart_values = [float(row['total']) for row in chart_results]

    # 6. FIX: Category Performance Data (Select c.name and Group by c.name)
    cursor.execute("""
        SELECT c.name, SUM(si.quantity) as count
        FROM sale_items si
        JOIN products p ON si.product_id = p.id
        JOIN categories c ON p.category_id = c.id
        GROUP BY c.name
    """)
    cat_results = cursor.fetchall()
    cat_labels = [row['name'] for row in cat_results]
    cat_values = [int(row['count']) for row in cat_results]

    # 7. Metrics (Correct as is)
    cursor.execute("SELECT AVG(total_amount) as avg FROM sales WHERE DATE(created_at) = CURDATE()")
    avg_sale = cursor.fetchone()['avg'] or 0
    
    cursor.execute("""
        SELECT 
            COALESCE(SUM(si.unit_price * si.quantity), 0) as revenue,
            COALESCE(SUM((si.unit_price - p.purchase_price) * si.quantity), 0) as profit
        FROM sale_items si
        JOIN products p ON si.product_id = p.id
        JOIN sales s ON si.sale_id = s.id
        WHERE DATE(s.created_at) = CURDATE()
    """)
    profit_data = cursor.fetchone()
    
    # Add error check for profit calculation
    revenue = profit_data['revenue'] or 0
    profit = profit_data['profit'] or 0
    profit_margin = round((profit / revenue * 100), 1) if revenue > 0 else 0

    today_date = datetime.now().strftime('%Y-%m-%d')
    
    return render_template('reports.html',
                           username=session['username'],
                           today=today,
                           total_products=total_products,
                           low_stock=low_stock,
                           top_products=top_products,
                           avg_sale=avg_sale,
                           profit_margin=profit_margin,
                           today_date=today_date,
                           # Match the names used in reports.html:
                           sales_labels=chart_labels, 
                           sales_values=chart_values,
                           cat_labels=cat_labels,
                           cat_values=cat_values)

@app.route('/api/recent_sales')
def recent_sales():
    if 'loggedin' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("""
        SELECT s.*, 
               (SELECT COUNT(*) FROM sale_items WHERE sale_id = s.id) as item_count
        FROM sales s
        ORDER BY s.created_at DESC
        LIMIT 10
    """)
    sales = cursor.fetchall()
    
    for sale in sales:
        # 1. Fix Decimal (for total_amount)
        if 'total_amount' in sale and sale['total_amount'] is not None:
            sale['total_amount'] = float(sale['total_amount'])
        
        # 2. FIX: Convert datetime to string (Critical for JSON)
        if 'created_at' in sale and sale['created_at'] is not None:
            # Format: '2023-10-27 14:30:00'
            sale['created_at'] = sale['created_at'].strftime('%Y-%m-%d %H:%M:%S')
    
    return jsonify(sales)

@app.route('/receipt/<int:sale_id>')
def view_receipt(sale_id):
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Fetch the main sale info
    cursor.execute("SELECT * FROM sales WHERE id = %s", (sale_id,))
    sale = cursor.fetchone()
    
    if not sale:
        return "<h1>Error: Receipt Not Found</h1>", 404

    # Fetch the items - using LEFT JOIN so receipt works even if product is deleted
    cursor.execute("""
        SELECT si.*, COALESCE(p.name, 'Deleted Product') as product_name
        FROM sale_items si
        LEFT JOIN products p ON si.product_id = p.id
        WHERE si.sale_id = %s
    """, (sale_id,))
    items = cursor.fetchall()
    
    return render_template('receipt.html', sale=sale, items=items)


# ========== CATEGORY MANAGEMENT ==========
@app.route('/categories')
def categories():
    if not session.get('loggedin'):
        flash('Please login first', 'error')
        return redirect(url_for('home'))
    
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM categories ORDER BY name")
    categories_list = cursor.fetchall()
    
    return render_template('categories.html',
                         username=session['username'],
                         categories=categories_list)

@app.route('/add_category', methods=['POST'])
def add_category():
    if not session.get('loggedin'):
        flash('Please login first', 'error')
        return redirect(url_for('home'))
    
    try:
        name = request.form.get('name')
        description = request.form.get('description', '')
        
        cursor = mysql.connection.cursor()
        cursor.execute("INSERT INTO categories (name, description) VALUES (%s, %s)",
                      (name, description))
        mysql.connection.commit()
        
        flash(f'✅ Category "{name}" added successfully!', 'success')
        
    except Exception as e:
        mysql.connection.rollback()
        flash(f'❌ Error: {str(e)}', 'error')
    
    return redirect(url_for('categories'))


@app.route('/delete_category/<int:id>')
def delete_category(id):
    if not session.get('loggedin'):
        return redirect(url_for('login'))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        # 1. Check if an "Uncategorized" category exists, if not, create it
        cursor.execute("SELECT id FROM categories WHERE name = 'Uncategorized'")
        uncat = cursor.fetchone()
        
        if not uncat:
            cursor.execute("INSERT INTO categories (name, description) VALUES ('Uncategorized', 'Default category')")
            uncat_id = cursor.lastrowid
        else:
            uncat_id = uncat['id']

        # 2. Prevent deleting the "Uncategorized" category itself
        if id == uncat_id:
            flash("❌ Cannot delete the default Uncategorized category.", "error")
            return redirect(url_for('categories'))

        # 3. Move all products in the category being deleted to "Uncategorized"
        cursor.execute("UPDATE products SET category_id = %s WHERE category_id = %s", (uncat_id, id))

        # 4. Now safely delete the category
        cursor.execute("DELETE FROM categories WHERE id = %s", (id,))
        
        mysql.connection.commit()
        flash("✅ Category removed. Linked products moved to 'Uncategorized'.", "success")
        
    except Exception as e:
        mysql.connection.rollback()
        flash(f"❌ Error: {str(e)}", "error")

    return redirect(url_for('categories'))

# ========== DEMO RESET BUTTON ==========
@app.route('/reset_demo')
def reset_demo():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    try:
        cursor = mysql.connection.cursor()
        
        # 1. Delete all sales
        cursor.execute("DELETE FROM sale_items")
        cursor.execute("DELETE FROM sales")
        
        # 2. Reset product stocks to 10
        cursor.execute("UPDATE products SET stock_quantity = 10")
        
        # 3. Clear all alerts
        cursor.execute("DELETE FROM alerts")
        
        mysql.connection.commit()
        flash('✅ Demo reset! All sales cleared and stocks reset.', 'success')
        
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('dashboard'))

# ==========================================
#        AI SMART FEATURES
# ==========================================

@app.route('/api/ai/recommendations/<int:product_id>')
def get_recommendations(product_id):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # AI Query: Find other products that appear in the same 'sale_id' as the current product
    query = """
        SELECT p.id, p.name, p.selling_price, p.stock_quantity, COUNT(*) as frequency
        FROM sale_items si1
        JOIN sale_items si2 ON si1.sale_id = si2.sale_id
        JOIN products p ON si2.product_id = p.id
        WHERE si1.product_id = %s 
        AND si2.product_id != %s
        AND p.stock_quantity > 0
        GROUP BY p.id
        ORDER BY frequency DESC
        LIMIT 1
    """
    cursor.execute(query, (product_id, product_id))
    suggestion = cursor.fetchone()
    
    if suggestion:
        suggestion['selling_price'] = float(suggestion['selling_price'])
        return jsonify([suggestion])
    return jsonify([])

@app.route('/api/ai/optimize_stock')
def optimize_stock():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    # Calculate average daily sales over the last 30 days
    cursor.execute("""
        SELECT product_id, SUM(quantity)/30 as daily_velocity
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE s.created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        GROUP BY product_id
    """)
    results = cursor.fetchall()
    
    for row in results:
        # AI Logic: New Min Stock = (Avg Daily Sales * 7 Days) + 20% Safety Buffer
        new_min = max(5, round((float(row['daily_velocity']) * 7) * 1.2))
        cursor.execute("UPDATE products SET min_stock_level = %s WHERE id = %s", (new_min, row['product_id']))
    
    mysql.connection.commit()
    return jsonify({"success": True, "message": "Inventory levels optimized based on sales trends!"})


@app.route('/api/ai/price_strategy/<int:product_id>')
def price_strategy(product_id):
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("""
            SELECT p.*, 
            (SELECT SUM(quantity) FROM sale_items WHERE product_id = p.id) as total_sold
            FROM products p WHERE p.id = %s
        """, (product_id,))
        product = cursor.fetchone()

        if not product:
            return jsonify({"error": "Product not found"}), 404

        # Convert Decimals/None to safe types
        cost = float(product['purchase_price'])
        current_price = float(product['selling_price'])
        sold = int(product['total_sold'] or 0)
        stock = int(product['stock_quantity'])

        # Groq works best with a system message and a user message
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a retail inventory optimizer. Your goal is to help clear slow-moving stock through discounts or protect margins for low-stock items. Always respond with ONLY a valid JSON object."
                },
                {
                    "role": "user", 
                    "content": f"""Analyze this product data for my college project:
                        Name: {product['name']}
                        Cost: ₹{cost}
                        Current Price: ₹{current_price}
                        Total Sold: {sold}
                        Stock Level: {stock}
                        
                        STRATEGY RULES:
                        1. If Stock is HIGH (e.g., > 10) and Sold is LOW (e.g., < 2), you MUST suggest 'Decrease' (a discount) to clear inventory.
                        2. If Selling Price is equal to or less than Cost, suggest 'Increase' to ensure a 20% profit margin.
                        3. If Stock is low (< 3) but it's selling, suggest 'Keep' or 'Increase' due to high demand.
                        4. Keep all price changes realistic (within 5-20% of the current price).

                        Return JSON format: 
                        {{"recommendation": "Increase/Decrease/Keep", "new_price": 0.0, "reason": "text"}}"""
                }
            ],
            response_format={"type": "json_object"}
        )

        # Groq output is very clean
        strategy = json.loads(completion.choices[0].message.content)
        return jsonify(strategy)

    except Exception as e:
        print(f"GROQ CRITICAL ERROR: {str(e)}") 
        return jsonify({"error": str(e)}), 500
# ---------- RUN APP ----------
if __name__ == '__main__':
    # Get port from Railway, default to 5001 for local testing
    port = int(os.getenv("PORT", 5001))
    # host='0.0.0.0' is required for cloud deployment
    app.run(host='0.0.0.0', port=port, debug=False)