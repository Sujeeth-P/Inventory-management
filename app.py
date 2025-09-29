from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, g
import sqlite3
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['DATABASE'] = 'inventory.db'

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

@app.teardown_appcontext
def close_db_handler(error):
    close_db()


@app.template_filter('datetime')
def datetime_filter(value):
    if value:
        try:
            # If it's already a string, return as is
            if isinstance(value, str):
                return value
            # If it's a datetime object, format it
            return value.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return str(value)
    return 'Not recorded'


def init_db():
    with app.app_context():
        db = get_db()
        db.executescript('''
            CREATE TABLE IF NOT EXISTS product (
                product_id VARCHAR(50) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT
            );
            
            CREATE TABLE IF NOT EXISTS location (
                location_id VARCHAR(50) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                address TEXT
            );
            
            CREATE TABLE IF NOT EXISTS product_movement (
                movement_id VARCHAR(50) PRIMARY KEY,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                from_location VARCHAR(50),
                to_location VARCHAR(50),
                product_id VARCHAR(50) NOT NULL,
                qty INTEGER NOT NULL,
                FOREIGN KEY (from_location) REFERENCES location (location_id),
                FOREIGN KEY (to_location) REFERENCES location (location_id),
                FOREIGN KEY (product_id) REFERENCES product (product_id)
            );
        ''')
        db.commit()

# Initialize database
with app.app_context():
    init_db()

@app.route('/')
def index():
    db = get_db()   
    
    try:
        # Get basic counts
        total_products = db.execute('SELECT COUNT(*) as count FROM product').fetchone()['count']
        total_locations = db.execute('SELECT COUNT(*) as count FROM location').fetchone()['count'] 
        total_movements = db.execute('SELECT COUNT(*) as count FROM product_movement').fetchone()['count']
        
        # Calculate total stock (items in minus items out)
        total_stock_in = db.execute('SELECT COALESCE(SUM(qty), 0) as total FROM product_movement WHERE to_location IS NOT NULL').fetchone()['total']
        total_stock_out = db.execute('SELECT COALESCE(SUM(qty), 0) as total FROM product_movement WHERE from_location IS NOT NULL').fetchone()['total']
        total_stock = total_stock_in - total_stock_out
        
        # Get stock by location
        stock_by_location = []
        locations = db.execute('SELECT location_id, name FROM location').fetchall()
        
        for location in locations:
            stock_in = db.execute(
                'SELECT COALESCE(SUM(qty), 0) as total FROM product_movement WHERE to_location = ?',
                (location['location_id'],)
            ).fetchone()['total']
            
            stock_out = db.execute(
                'SELECT COALESCE(SUM(qty), 0) as total FROM product_movement WHERE from_location = ?',
                (location['location_id'],)
            ).fetchone()['total']
            
            net_stock = stock_in - stock_out
            if net_stock > 0:
                stock_by_location.append({
                    'location': location['name'], 
                    'stock': net_stock
                })
        
        # Get product distribution
        product_distribution = []
        products = db.execute('SELECT product_id, name FROM product').fetchall()
        
        for product in products:
            stock_in = db.execute(
                'SELECT COALESCE(SUM(qty), 0) as total FROM product_movement WHERE product_id = ? AND to_location IS NOT NULL',
                (product['product_id'],)
            ).fetchone()['total']
            
            stock_out = db.execute(
                'SELECT COALESCE(SUM(qty), 0) as total FROM product_movement WHERE product_id = ? AND from_location IS NOT NULL',
                (product['product_id'],)
            ).fetchone()['total']
            
            net_stock = stock_in - stock_out
            if net_stock > 0:
                product_distribution.append({
                    'product': product['name'], 
                    'stock': net_stock
                })
        
        # Get movement types
        movement_types = []
        movement_type_query = db.execute('''
            SELECT 
                CASE 
                    WHEN from_location IS NULL AND to_location IS NOT NULL THEN 'Stock In'
                    WHEN from_location IS NOT NULL AND to_location IS NULL THEN 'Stock Out'
                    WHEN from_location IS NOT NULL AND to_location IS NOT NULL THEN 'Transfer'
                    ELSE 'Unknown'
                END as movement_type,
                COUNT(*) as count
            FROM product_movement
            GROUP BY movement_type
        ''').fetchall()
        
        for row in movement_type_query:
            movement_types.append({
                'type': row['movement_type'], 
                'count': row['count']
            })
        
        # Get low stock products (less than 10 units)
        low_stock = []
        for product in products:
            stock_in = db.execute(
                'SELECT COALESCE(SUM(qty), 0) as total FROM product_movement WHERE product_id = ? AND to_location IS NOT NULL',
                (product['product_id'],)
            ).fetchone()['total']
            
            stock_out = db.execute(
                'SELECT COALESCE(SUM(qty), 0) as total FROM product_movement WHERE product_id = ? AND from_location IS NOT NULL',
                (product['product_id'],)
            ).fetchone()['total']
            
            net_stock = stock_in - stock_out
            if 0 < net_stock < 10:
                low_stock.append({
                    'id': product['product_id'],
                    'name': product['name'],
                    'stock': net_stock
                })
        
        # Package all dashboard data
        dashboard_data = {
            'total_products': total_products,
            'total_locations': total_locations,
            'total_movements': total_movements,
            'total_stock': max(0, total_stock),  # Don't show negative stock
            'stock_by_location': stock_by_location,
            'product_distribution': product_distribution,
            'movement_types': movement_types,
            'low_stock': low_stock
        }
        
        return render_template('index.html',
                             dashboard_data=dashboard_data,
                             current_time=datetime.utcnow().strftime('%a, %I:%M %p'))
    
    except Exception as e:
        print(f"Dashboard Error: {str(e)}")
        # Return empty dashboard data if there's an error
        dashboard_data = {
            'total_products': 0,
            'total_locations': 0,
            'total_movements': 0,
            'total_stock': 0,
            'stock_by_location': [],
            'product_distribution': [],
            'movement_types': [],
            'low_stock': []
        }
        
        return render_template('index.html',
                             dashboard_data=dashboard_data,
                             current_time=datetime.utcnow().strftime('%a, %I:%M %p'),
                             error_message=f"Dashboard error: {str(e)}")



# Product Routes
@app.route('/products')
def products():
    db = get_db()
    products = db.execute('SELECT * FROM product ORDER BY product_id').fetchall()
    return render_template('products.html', products=products)

@app.route('/product/add', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        product_id = request.form['product_id']
        name = request.form['name']
        description = request.form['description']
        
        db = get_db()
        
        # Check if product exists
        existing = db.execute('SELECT COUNT(*) FROM product WHERE product_id = ?', (product_id,)).fetchone()[0]
        
        if existing > 0:
            flash('Product ID already exists!', 'error')
        else:
            db.execute(
                'INSERT INTO product (product_id, name, description) VALUES (?, ?, ?)',
                (product_id, name, description)
            )
            db.commit()
            flash('Product added successfully!', 'success')
            return redirect(url_for('products'))
    
    return render_template('add_product.html')

@app.route('/product/edit/<product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    db = get_db()
    product = db.execute('SELECT * FROM product WHERE product_id = ?', (product_id,)).fetchone()
    
    if not product:
        flash('Product not found!', 'error')
        return redirect(url_for('products'))
    
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        
        db.execute(
            'UPDATE product SET name = ?, description = ? WHERE product_id = ?',
            (name, description, product_id)
        )
        db.commit()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('products'))
    
    return render_template('edit_product.html', product=product)

@app.route('/product/view/<product_id>')
def view_product(product_id):
    db = get_db()
    product = db.execute('SELECT * FROM product WHERE product_id = ?', (product_id,)).fetchone()
    
    if not product:
        flash('Product not found!', 'error')
        return redirect(url_for('products'))
    
    return render_template('view_product.html', product=product)

# Location Routes
@app.route('/locations')
def locations():
    db = get_db()
    locations = db.execute('SELECT * FROM location ORDER BY location_id').fetchall()
    return render_template('locations.html', locations=locations)

@app.route('/location/add', methods=['GET', 'POST'])
def add_location():
    if request.method == 'POST':
        location_id = request.form['location_id']
        name = request.form['name']
        address = request.form['address']
        
        db = get_db()
        
        # Check if location exists
        existing = db.execute('SELECT COUNT(*) FROM location WHERE location_id = ?', (location_id,)).fetchone()[0]
        
        if existing > 0:
            flash('Location ID already exists!', 'error')
        else:
            db.execute(
                'INSERT INTO location (location_id, name, address) VALUES (?, ?, ?)',
                (location_id, name, address)
            )
            db.commit()
            flash('Location added successfully!', 'success')
            return redirect(url_for('locations'))
    
    return render_template('add_location.html')

@app.route('/location/edit/<location_id>', methods=['GET', 'POST'])
def edit_location(location_id):
    db = get_db()
    location = db.execute('SELECT * FROM location WHERE location_id = ?', (location_id,)).fetchone()
    
    if not location:
        flash('Location not found!', 'error')
        return redirect(url_for('locations'))
    
    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        
        db.execute(
            'UPDATE location SET name = ?, address = ? WHERE location_id = ?',
            (name, address, location_id)
        )
        db.commit()
        flash('Location updated successfully!', 'success')
        return redirect(url_for('locations'))
    
    return render_template('edit_location.html', location=location)

@app.route('/location/view/<location_id>')
def view_location(location_id):
    db = get_db()
    location = db.execute('SELECT * FROM location WHERE location_id = ?', (location_id,)).fetchone()
    
    if not location:
        flash('Location not found!', 'error')
        return redirect(url_for('locations'))
    
    return render_template('view_location.html', location=location)

# ProductMovement Routes
@app.route('/movements')
def movements():
    db = get_db()
    query = '''
        SELECT pm.*, p.name as product_name, 
               fl.name as from_location_name, tl.name as to_location_name
        FROM product_movement pm
        LEFT JOIN product p ON pm.product_id = p.product_id
        LEFT JOIN location fl ON pm.from_location = fl.location_id
        LEFT JOIN location tl ON pm.to_location = tl.location_id
        ORDER BY pm.timestamp DESC
    '''
    movements = db.execute(query).fetchall()
    return render_template('movements.html', movements=movements)

@app.route('/movement/add', methods=['GET', 'POST'])
def add_movement():
    db = get_db()
    
    if request.method == 'POST':
        movement_id = request.form['movement_id']
        from_location = request.form['from_location'] if request.form['from_location'] else None
        to_location = request.form['to_location'] if request.form['to_location'] else None
        product_id = request.form['product_id']
        qty = int(request.form['qty'])
        
        # Check if movement exists
        existing = db.execute('SELECT COUNT(*) FROM product_movement WHERE movement_id = ?', (movement_id,)).fetchone()[0]
        
        if existing > 0:
            flash('Movement ID already exists!', 'error')
        elif not from_location and not to_location:
            flash('At least one location (from or to) must be specified!', 'error')
        else:
            db.execute(
                'INSERT INTO product_movement (movement_id, from_location, to_location, product_id, qty) VALUES (?, ?, ?, ?, ?)',
                (movement_id, from_location, to_location, product_id, qty)
            )
            db.commit()
            flash('Movement added successfully!', 'success')
            return redirect(url_for('movements'))
    
    products = db.execute('SELECT * FROM product ORDER BY product_id').fetchall()
    locations = db.execute('SELECT * FROM location ORDER BY location_id').fetchall()
    return render_template('add_movement.html', products=products, locations=locations)

@app.route('/movement/edit/<movement_id>', methods=['GET', 'POST'])
def edit_movement(movement_id):
    db = get_db()
    movement = db.execute('SELECT * FROM product_movement WHERE movement_id = ?', (movement_id,)).fetchone()
    
    if not movement:
        flash('Movement not found!', 'error')
        return redirect(url_for('movements'))
    
    if request.method == 'POST':
        from_location = request.form['from_location'] if request.form['from_location'] else None
        to_location = request.form['to_location'] if request.form['to_location'] else None
        product_id = request.form['product_id']
        qty = int(request.form['qty'])
        
        if not from_location and not to_location:
            flash('At least one location (from or to) must be specified!', 'error')
        else:
            db.execute(
                'UPDATE product_movement SET from_location = ?, to_location = ?, product_id = ?, qty = ? WHERE movement_id = ?',
                (from_location, to_location, product_id, qty, movement_id)
            )
            db.commit()
            flash('Movement updated successfully!', 'success')
            return redirect(url_for('movements'))
    
    products = db.execute('SELECT * FROM product ORDER BY product_id').fetchall()
    locations = db.execute('SELECT * FROM location ORDER BY location_id').fetchall()
    return render_template('edit_movement.html', movement=movement, products=products, locations=locations)

@app.route('/movement/view/<movement_id>')
def view_movement(movement_id):
    db = get_db()
    query = '''
        SELECT pm.*, p.name as product_name, 
               fl.name as from_location_name, tl.name as to_location_name
        FROM product_movement pm
        LEFT JOIN product p ON pm.product_id = p.product_id
        LEFT JOIN location fl ON pm.from_location = fl.location_id
        LEFT JOIN location tl ON pm.to_location = tl.location_id
        WHERE pm.movement_id = ?
    '''
    movement = db.execute(query, (movement_id,)).fetchone()
    
    if not movement:
        flash('Movement not found!', 'error')
        return redirect(url_for('movements'))
    
    return render_template('view_movement.html', movement=movement)

# Balance Report Route using SQL
@app.route('/balance')
def balance_report():
    db = get_db()
    
    # SQL query to calculate balance for each product in each location
    query = '''
        WITH movement_balance AS (
            -- Movements into locations (positive quantity)
            SELECT 
                product_id,
                to_location as location_id,
                SUM(qty) as balance
            FROM product_movement 
            WHERE to_location IS NOT NULL
            GROUP BY product_id, to_location
            
            UNION ALL
            
            -- Movements out of locations (negative quantity)
            SELECT 
                product_id,
                from_location as location_id,
                SUM(-qty) as balance
            FROM product_movement 
            WHERE from_location IS NOT NULL
            GROUP BY product_id, from_location
        ),
        final_balance AS (
            SELECT 
                product_id,
                location_id,
                SUM(balance) as total_qty
            FROM movement_balance
            GROUP BY product_id, location_id
            HAVING SUM(balance) != 0
        )
        SELECT 
            fb.product_id,
            p.name as product_name,
            fb.location_id,
            l.name as location_name,
            fb.total_qty
        FROM final_balance fb
        JOIN product p ON fb.product_id = p.product_id
        JOIN location l ON fb.location_id = l.location_id
        ORDER BY p.name, l.name
    '''
    
    balance_data = db.execute(query).fetchall()
    return render_template('balance_report.html', balance_data=balance_data)


if __name__ == '__main__':
    app.run(debug=True)
