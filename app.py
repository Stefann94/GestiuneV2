import io
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, 
    flash, jsonify, send_file, session, abort
)

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash, check_password_hash

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
app.secret_key = "cheie_secreta_pentru_sesiuni"

def get_db_connection():
    try:
        conn = psycopg2.connect(
            host="localhost",
            database="site_gestiune", 
            user="postgres",
            password="adsjhfhjngjewfwedkasmdqiwe8327428374n8237wqxemoiew" 
        )
        return conn
    except Exception as e:
        print(f"Eroare la conectarea DB: {e}")
        return None


def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_role = session.get('role', '').lower().strip()
            
            if user_role not in [r.lower() for r in roles]:
                return jsonify({
                    "status": "error", 
                    "message": "Acces interzis! Doar Adminii sau Ownerii pot modifica prețurile."
                }), 403
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: 
        return "Eroare la baza de date!"
    
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        query_products = """
            SELECT p.*, 
            (COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
             COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0)) as current_calculated_stock
            FROM products p;
        """
        cur.execute(query_products)
        products = cur.fetchall()
        
        
        cur.execute("SELECT COUNT(*) as total FROM products;")
        total_items = cur.fetchone()['total'] or 0
        
        cur.execute("SELECT COUNT(*) as alerts FROM products WHERE last_audit_status = 'shortage';")
        shortage_alerts = cur.fetchone()['alerts'] or 0
        
        query_moves = """
            SELECT (
                (SELECT COUNT(*) FROM stock_entries WHERE entry_date::date = CURRENT_DATE) +
                (SELECT COUNT(*) FROM stock_exits WHERE exit_date::date = CURRENT_DATE) +
                (SELECT COUNT(*) FROM products WHERE updated_at::date = CURRENT_DATE)
            ) as moves_today;
        """
        cur.execute(query_moves)
        moves_today = cur.fetchone()['moves_today'] or 0
        
        stats = {
            'total': total_items, 
            'alerts': shortage_alerts, 
            'moves': moves_today
        }
        
        critical_products = [p for p in products if (p['current_calculated_stock'] or 0) <= (p['stock_min'] or 0)]
        
        cur.execute("SELECT * FROM categories ORDER BY name ASC;")
        categories = cur.fetchall()

    except Exception as e:
        print(f"Eroare la procesarea datelor: {e}")
        return f"Eroare sistem: {e}"
    finally:
        cur.close()
        conn.close()
    
    return render_template('index.html', 
                           products=products, 
                           stats=stats, 
                           critical_products=critical_products[:5], 
                           categories=categories)

@app.route('/produse')
def produse():
    conn = get_db_connection()
    if not conn: return "Eroare la baza de date!"
    cur = conn.cursor(cursor_factory=RealDictCursor)
    query = """
        SELECT p.id, p.name, p.sku, p.price, p.stock_min,
        (COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
         COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0)) as stock
        FROM products p
        ORDER BY p.id DESC;
    """
    cur.execute(query)
    all_products = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('produse.html', products=all_products)

@app.route('/inventar')
def inventar():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    query = """
    SELECT 
        p.id,
        p.name,
        p.sku,
        p.last_audit_status,
        p.last_audit_diff,
        p.last_faptic_value,

        COALESCE(
            p.last_system_stock,
            (
                COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id),0)
                -
                COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id),0)
            )
        ) as stock_sistem,

        COALESCE(
            p.last_faptic_value,
            (
                COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id),0)
                -
                COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id),0)
            )
        ) as stock_faptic

    FROM products p;
    """
    cur.execute(query)
    products = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('inventar.html', products=products)


@app.route('/add_product', methods=['POST'])
@roles_required('admin', 'owner')
def add_product():
    name = request.form['name']
    sku = request.form['sku']
    stock_min = request.form['stock_min']
    
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute("""
                INSERT INTO products (name, sku, stock_min, last_system_stock, last_faptic_value) 
                VALUES (%s, %s, %s, 0, 0) RETURNING id
            """, (name, sku, stock_min))
            
            new_id = cur.fetchone()['id']
            
            cur.execute("""
                INSERT INTO inventory_history 
                (product_id, product_name, type, old_system_stock, new_system_stock, old_faptic_stock, new_faptic_stock)
                VALUES (%s, %s, %s, 0, 0, 0, 0)
            """, (new_id, name, 'ADAUGARE PRODUS'))
            
            conn.commit()
        except Exception as e:
            if conn: conn.rollback()
            print(f"Eroare la adaugare produs: {e}")
        finally:
            cur.close()
            conn.close()
            
    return redirect(url_for('index'))

@app.route('/produse/nou', methods=['POST'])
@roles_required('admin', 'owner')
def produs_nou():
    name = request.form.get('name')
    sku = request.form.get('sku')
    price = request.form.get('price')
    stock_min = request.form.get('stock_min')
    category_id = request.form.get('category_id')
    
    sys_stock = int(request.form.get('system_stock', 0))
    fap_stock = int(request.form.get('faptic_stock', 0))
    
    diff = fap_stock - sys_stock
    audit_status = 'synced' if diff == 0 else ('shortage' if diff < 0 else 'surplus')

    conn = get_db_connection()
    if not conn: 
        return jsonify({"status": "error", "message": "Conexiune DB eșuată"}), 500
    
    try:
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO products (name, sku, price, category_id, stock_min, last_system_stock, 
                                last_faptic_value, last_audit_diff, last_audit_status, updated_at) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """, (name, sku, float(price) if price else 0, category_id, 
              int(stock_min) if stock_min else 0, sys_stock, fap_stock, diff, audit_status))
        
        product_id = cur.fetchone()[0]

        if fap_stock > 0:
            cur.execute("""
                INSERT INTO stock_entries (product_id, quantity, entry_date)
                VALUES (%s, %s, NOW())
            """, (product_id, fap_stock))

        product_label = f"{name} [{sku}]" if sku else name
        cur.execute("""
            INSERT INTO inventory_history 
            (product_id, product_name, type, old_system_stock, new_system_stock, old_faptic_stock, new_faptic_stock)
            VALUES (%s, %s, 'ADAUGARE PRODUS', 0, %s, 0, %s)
        """, (product_id, product_label, sys_stock, fap_stock))

        conn.commit()
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"Eroare adăugare produs: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400
    finally:
        cur.close()
        conn.close()


@app.route('/api/v1/internal/inventory-leakage-detector')
def inventory_leakage_detector():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    query = """
        SELECT 
            id,
            name, 
            COALESCE(last_faptic_value, 0) as stock_faptic, 
            COALESCE(last_system_stock, 0) as stock_system,
            (COALESCE(last_system_stock, 0) - COALESCE(last_faptic_value, 0)) as deficit
        FROM products 
        WHERE last_faptic_value < last_system_stock
        ORDER BY deficit DESC
        LIMIT 20;
    """
    
    try:
        cur.execute(query)
        rows = cur.fetchall()
        return jsonify({
            "status": "success",
            "count": len(rows),
            "data": rows
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/panou')
def orice_nume():
    return render_template('panou.html')


@app.route('/api/v1/internal/inventory-omnisearch')
def inventory_omnisearch():
    term = request.args.get('term', '').strip()
    
    if not term:
        return jsonify({"status": "empty", "results": []})

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    query = """
        SELECT 
            id, 
            name, 
            sku, 
            price, 
            last_faptic_value as stock,
            last_audit_status as status
        FROM products 
        WHERE (name ILIKE %s OR sku ILIKE %s)
        ORDER BY name ASC
        LIMIT 15;
    """
    
    try:
        search_pattern = f"%{term}%"
        cur.execute(query, (search_pattern, search_pattern))
        rows = cur.fetchall()
        
        return jsonify({
            "status": "success",
            "count": len(rows),
            "data": rows
        })
        
    except Exception as e:
        print(f"CRITICAL SEARCH ERROR: {e}")
        return jsonify({"status": "error", "message": "Eroare la procesarea căutării"}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/audit-save', methods=['POST'])
@roles_required('admin', 'owner')
def audit_save():
    data = request.json
    p_id = data.get('id')
    noua_valoare_faptica = int(data.get('stock'))
    
    conn = get_db_connection()
    if not conn: 
        return jsonify({"status": "error", "message": "DB Connection Error"}), 500
    
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("SELECT name, last_system_stock, last_faptic_value FROM products WHERE id = %s", (p_id,))
        old_prod = cur.fetchone()

        cur.execute("""
            SELECT (
                COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = %s), 0) - 
                COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = %s), 0)
            ) as stoc_sistem
        """, (p_id, p_id))
        
        row = cur.fetchone()
        stoc_sistem = row['stoc_sistem'] if row else 0
        
        diferenta_noua = noua_valoare_faptica - stoc_sistem
        status_nou = 'synced' if diferenta_noua == 0 else ('shortage' if diferenta_noua < 0 else 'surplus')

        cur.execute("""
            UPDATE products 
            SET last_faptic_value = %s,
                last_system_stock = %s,
                last_audit_diff = %s,
                last_audit_status = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (noua_valoare_faptica, stoc_sistem, diferenta_noua, status_nou, p_id))

        cur.execute("""
            INSERT INTO inventory_history 
            (product_id, product_name, type, old_system_stock, new_system_stock, old_faptic_stock, new_faptic_stock)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            p_id, 
            old_prod['name'], 
            'MODIFICARE STOC', 
            old_prod['last_system_stock'] or 0, 
            stoc_sistem, 
            old_prod['last_faptic_value'] or 0, 
            noua_valoare_faptica
        ))
        
        conn.commit()
        
        return jsonify({
            "status": "success",
            "message": "Audit salvat! Mișcarea a fost înregistrată.",
            "new_faptic": noua_valoare_faptica,
            "new_status": status_nou,
            "new_diff": diferenta_noua
        })
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"Eroare la salvare audit: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400
    finally:
        cur.close()
        conn.close()

@app.route('/api/stats/reports')
def get_reports_stats():
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB connection failed"}), 500
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        query_stats = """
            SELECT COUNT(*) as total_items,
                   COUNT(*) FILTER (WHERE last_audit_status = 'synced' OR last_audit_status IS NULL) as total_ok,
                   ABS(COALESCE(SUM(last_audit_diff) FILTER (WHERE last_audit_diff < 0), 0)) as total_shortage,
                   COALESCE(SUM(last_audit_diff) FILTER (WHERE last_audit_diff > 0), 0) as total_surplus
            FROM products;
        """
        cur.execute(query_stats)
        stats = cur.fetchone()
        cur.execute("SELECT name, sku, last_audit_status, last_audit_diff FROM products ORDER BY name ASC;")
        products = cur.fetchall()
        return jsonify({"stats": stats, "products": products})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/rapoarte/export/<format>')
def export_rapoarte(format):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT name, sku, last_audit_status, last_audit_diff FROM products ORDER BY name ASC;")
        data = cur.fetchall()
        timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M")

        if format == 'excel':
            df = pd.DataFrame(data)
            df.columns = ['Nume Produs', 'Cod SKU', 'Status Audit', 'Diferenta']
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Audit')
            output.seek(0)
            return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                             as_attachment=True, download_name=f"Raport_Audit_{timestamp}.xlsx")

        elif format == 'pdf':
            output = io.BytesIO()
            doc = SimpleDocTemplate(output, pagesize=A4)
            elements = []
            styles = getSampleStyleSheet()
            elements.append(Paragraph("Raport Audit Inventar", styles['Title']))
            elements.append(Paragraph(f"Generat la: {datetime.now().strftime('%d.%m.%Y %H:%M')}", styles['Normal']))
            elements.append(Spacer(1, 12))

            table_data = [['Produs', 'SKU', 'Status', 'Diferenta']]
            for row in data:
                table_data.append([row['name'], row['sku'], (row['last_audit_status'] or 'synced').upper(), f"{row['last_audit_diff']:+d}"])

            t = Table(table_data, colWidths=[200, 100, 100, 80])
            t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#064e3b')),
                                   ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                                   ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                   ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)]))
            elements.append(t)
            doc.build(elements)
            output.seek(0)
            return send_file(output, mimetype='application/pdf', as_attachment=True, download_name=f"Raport_Audit_{timestamp}.pdf")
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/stats/stock-flow')
def stock_flow():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    query = """
        SELECT TO_CHAR(d.day, 'Dy') as zi, COALESCE(SUM(se.quantity), 0) as total
        FROM generate_series(CURRENT_DATE - INTERVAL '6 days', CURRENT_DATE, '1 day') d(day)
        LEFT JOIN stock_exits se ON se.exit_date::date = d.day::date
        GROUP BY d.day ORDER BY d.day ASC;
    """
    try:
        cur.execute(query)
        results = cur.fetchall()
        zile_ro = {'Mon': 'Lun', 'Tue': 'Mar', 'Wed': 'Mie', 'Thu': 'Joi', 'Fri': 'Vin', 'Sat': 'Sâm', 'Sun': 'Dum'}
        return jsonify({
            "labels": [zile_ro.get(row['zi'], row['zi']) for row in results],
            "values": [float(row['total']) for row in results]
        })
    finally:
        conn.close()

@app.route('/dashboard')
def dashboard():
    conn = get_db_connection()
    if not conn: 
        return "Eroare la conexiunea cu baza de date!"
    
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        query_valoare = """
            SELECT SUM(p.price * (
                COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
                COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0)
            )) as total_valoare FROM products p;
        """
        cur.execute(query_valoare)
        valoare_inventar = cur.fetchone()['total_valoare'] or 0

        query_urgente_count = """
            SELECT COUNT(*) as count FROM (
                SELECT 
                    p.id,
                    (COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
                     COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0)) as stoc_sistem,
                    COALESCE(p.last_faptic_value, 
                        (COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
                         COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0))
                    ) as stoc_faptic
                FROM products p
            ) as inv 
            WHERE inv.stoc_faptic < 20 
              AND inv.stoc_faptic < inv.stoc_sistem;
        """
        cur.execute(query_urgente_count)
        urgente_count = cur.fetchone()['count'] or 0

        cur.execute("""
            SELECT SUM(quantity) as iesiri 
            FROM stock_exits 
            WHERE exit_date > NOW() - INTERVAL '24 hours';
        """)
        flux_iesiri = cur.fetchone()['iesiri'] or 0

        cur.execute("SELECT COUNT(*) as count FROM categories;")
        categorii_totale = cur.fetchone()['count'] or 0

        query_critice = """
            SELECT p.name, p.stock_min,
            (COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
             COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0)) as stock
            FROM products p
            WHERE (
                COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
                COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0)
            ) <= 20
            ORDER BY stock ASC
            LIMIT 10;
        """
        cur.execute(query_critice)
        produse_critice = cur.fetchall()

        return render_template('panou.html', 
                               valoare=valoare_inventar, 
                               urgente=urgente_count, 
                               flux=flux_iesiri,
                               nr_categorii=categorii_totale,
                               critice=produse_critice)

    except Exception as e:
        print(f"Eroare Dashboard: {e}")
        return f"A intervenit o eroare la procesarea datelor: {e}"
    
    finally:
        cur.close()
        conn.close()
    
@app.route('/api/stats/categorii')
def stats_categorii():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    query = """
        SELECT c.name as categorie, SUM(p.price * (
            COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
            COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0)
        )) as valoare
        FROM products p
        JOIN categories c ON p.category_id = c.id
        GROUP BY c.name;
    """
    
    try:
        cur.execute(query)
        rows = cur.fetchall()
        
        if not rows:
            return jsonify({"labels": ["Fără date"], "values": [0]})

        return jsonify({
            "labels": [r['categorie'] for r in rows],
            "values": [float(r['valoare']) for r in rows]
        })
    except Exception as e:
        print(f"Eroare SQL: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/stats/top-produse')
def top_produse():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "DB connection failed"}), 500
    
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT name, price FROM products ORDER BY price DESC LIMIT 5;")
        scumpe = cur.fetchall()

        cur.execute("""
            SELECT name, 
                   (last_system_stock - last_faptic_value) as total_vandut
            FROM products 
            WHERE last_audit_status = 'shortage' 
              AND last_system_stock > last_faptic_value
            ORDER BY total_vandut DESC
            LIMIT 5;
        """)
        vandute = cur.fetchall()

        return jsonify({
            "scumpe": scumpe,
            "vandute": vandute
        })
    except Exception as e:
        print(f"Eroare API top-produse: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/stats/urgente-detaliate')
def urgente_detaliate():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "DB connection failed"}), 500
    
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        query = """
            WITH StockData AS (
                SELECT
                    p.id, 
                    p.name, 
                    p.sku,
                    p.price,
                    -- Calculăm Stoc Sistem (Intrări - Ieșiri)
                    (COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
                     COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0)) as stoc_sistem,
                    
                    -- Calculăm Stoc Faptic (Ultimul audit sau calculul matematic)
                    COALESCE(p.last_faptic_value, 
                        (COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
                         COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0))
                    ) as stoc_faptic
                FROM products p
            )
            SELECT * FROM StockData
            WHERE 
                stoc_faptic < 20             -- Regula 1: Fapticul să fie sub 20
                AND stoc_faptic < stoc_sistem -- Regula 2: Fapticul să fie mai mic decât sistemul (lipsă stoc)
            ORDER BY stoc_faptic ASC;
        """
        cur.execute(query)
        produse = cur.fetchall()

        categorii = {
            "critice": [p for p in produse if p['stoc_faptic'] <= 0],
            "limitate": [p for p in produse if 0 < p['stoc_faptic'] <= 10],
            "atentie": [p for p in produse if 10 < p['stoc_faptic'] < 20]
        }
        
        return jsonify(categorii)
    except Exception as e:
        print(f"Eroare Urgente: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/stats-quick')
def get_quick_stats():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    query_moves = """
    SELECT (
        (SELECT COUNT(*) FROM stock_entries WHERE entry_date::date = CURRENT_DATE) +
        (SELECT COUNT(*) FROM stock_exits WHERE exit_date::date = CURRENT_DATE) +
        (SELECT COUNT(*) FROM products WHERE updated_at::date = CURRENT_DATE)
    ) as moves_today,
        (SELECT COUNT(*) FROM products) as total_items,
        (SELECT COUNT(*) FROM products WHERE last_audit_status = 'shortage') as alerts;
    """
    cur.execute(query_moves)
    stats = cur.fetchone()
    conn.close()
    return jsonify(stats)


@app.route('/api/stats/categorii-active')
def stats_categorii_active():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "DB connection failed"}), 500
    
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        query = """
        WITH ProductStock AS (
            SELECT
                p.id,
                p.name,
                p.category_id,
                p.price,
                COALESCE(p.last_faptic_value, 0) as stock_faptic,
                (COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) -
                 COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0)) as stock_sistem
            FROM products p
        )
        SELECT 
            c.id as cat_id,
            c.name as categorie,
            COUNT(ps.id) as nr_produse,
            SUM(ps.price * ps.stock_sistem) as valoare_totala_categorie,
            -- Subquery pentru produsul cu diferența maximă (Sistem - Faptic)
            (SELECT ps2.name 
             FROM ProductStock ps2 
             WHERE ps2.category_id = c.id 
               AND ps2.stock_faptic < ps2.stock_sistem
             ORDER BY (ps2.stock_sistem - ps2.stock_faptic) DESC 
             LIMIT 1) as top_produs_nume,
            (SELECT (ps2.stock_sistem - ps2.stock_faptic)
             FROM ProductStock ps2 
             WHERE ps2.category_id = c.id 
               AND ps2.stock_faptic < ps2.stock_sistem
             ORDER BY (ps2.stock_sistem - ps2.stock_faptic) DESC 
             LIMIT 1) as top_produs_dif
        FROM categories c
        LEFT JOIN ProductStock ps ON c.id = ps.category_id
        GROUP BY c.id, c.name
        HAVING COUNT(ps.id) > 0
        ORDER BY valoare_totala_categorie DESC;
        """
        cur.execute(query)
        rows = cur.fetchall()

        return jsonify({
            "detalii": [
                {
                    "nume": r["categorie"],
                    "produse": r["nr_produse"],
                    "valoare": float(r["valoare_totala_categorie"] or 0),
                    "top_produs": {
                        "nume": r["top_produs_nume"],
                        "diferenta": int(r["top_produs_dif"] or 0)
                    } if r["top_produs_nume"] else None
                } for r in rows
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/stats/flux-iesiri')
def get_flux_iesiri():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT 
                p.name as nume, 
                c.name as categorie, 
                p.price as pret, 
                p.last_system_stock as sistem, 
                p.last_faptic_value as faptic
            FROM products p
            JOIN categories c ON p.category_id = c.id
            WHERE p.last_system_stock > p.last_faptic_value
        """)
        produse = cur.fetchall()
        
        iesiri = []
        for p in produse:
            sistem = p['sistem'] if p['sistem'] is not None else 0
            faptic = p['faptic'] if p['faptic'] is not None else 0
            dif = sistem - faptic
            
            if dif > 0:
                iesiri.append({
                    "nume": p['nume'],
                    "categorie": p['categorie'],
                    "pret": float(p['pret']),
                    "unitati": int(dif)
                })

        iesiri = sorted(iesiri, key=lambda x: x['unitati'], reverse=True)
        return jsonify(iesiri)

    except Exception as e:
        print(f"Eroare SQL Flux: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()
        
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    full_name = data.get('full_name')
    
    if not username or not password or not full_name:
        return jsonify({"status": "error", "message": "Toate câmpurile sunt obligatorii!"}), 400

    hashed_pw = generate_password_hash(password)
    
    conn = get_db_connection()
    if not conn: 
        return jsonify({"status": "error", "message": "Eroare conexiune DB"}), 500
    
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO users (username, password_hash, full_name, role, created_at)
            VALUES (%s, %s, %s, 'pending', NOW())
        """, (username, hashed_pw, full_name))
        
        conn.commit()
        return jsonify({"status": "success", "message": "Utilizator înregistrat cu succes! Contul este în așteptare."})

    except Exception as e:
        conn.rollback()
        error_msg = str(e)
        
        if "unique" in error_msg.lower():
            return jsonify({"status": "error", "message": "Numele de utilizator este deja luat!"}), 400
        elif "check constraint" in error_msg.lower():
            return jsonify({"status": "error", "message": "Rolul 'pending' nu este permis de baza de date. Rulează SQL-ul de update!"}), 400
        
        return jsonify({"status": "error", "message": "Eroare neprevăzută la înregistrare."}), 500
        
    finally:
        cur.close()
        conn.close()


@app.route('/api/bulk-price-update', methods=['POST'])
@roles_required('admin', 'owner')
def bulk_price_update():
    data = request.get_json()
    percent = data.get('percent')
    
    if percent is None:
        return jsonify({"status": "error", "message": "Procentul lipsește"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("UPDATE products SET price = price * (1 + %s / 100.0)", (percent,))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "status": "success", 
            "message": f"Prețurile au fost actualizate cu {percent}% de către {session.get('username')}"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cur.fetchone()

    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        
        cur.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user['id'],))
        conn.commit()
        conn.close()
        
        return jsonify({"status": "success", "redirect": url_for('dashboard')})
    
    conn.close()
    return jsonify({"status": "error", "message": "Utilizator sau parolă incorectă!"}), 401  


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"status": "success"})

@app.route('/api/get_all_users_with_roles', methods=['GET'])
def get_all_users_with_roles():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor) 
    try:
        query = """
            SELECT 
                id, 
                username, 
                full_name, 
                LOWER(TRIM(role)) as role 
            FROM users 
            ORDER BY created_at DESC
        """
        cur.execute(query)
        users = cur.fetchall()
        return jsonify(users)
    except Exception as e:
        print(f"Eroare API utilizatori: {e}")
        return jsonify([]), 500
    finally:
        cur.close()
        conn.close()
        
        
@app.route('/api/update_user_role', methods=['POST'])
def update_user_role():
    if session.get('role') != 'owner':
        return jsonify({"status": "error", "message": "Doar Owner-ul poate promova alți Owneri!"}), 403

    data = request.json
    user_id = data.get('id')
    new_role = data.get('role').lower()
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET role = %s WHERE id = %s", (new_role, user_id))
        
        conn.commit()
        return jsonify({"status": "success", "message": f"Utilizator actualizat la {new_role}!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/user/approve/<int:target_user_id>', methods=['POST'])
def approve_user(target_user_id):
    if session.get('role') not in ['owner', 'admin']:
        return jsonify({"status": "error", "message": "Acces interzis!"}), 403

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET role = 'operator' WHERE id = %s AND role = 'pending'", (target_user_id,))
        conn.commit()
        return jsonify({"status": "success", "message": "Utilizator aprobat!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/user/promote/<int:target_user_id>', methods=['POST'])
def promote_to_admin(target_user_id):
    if session.get('role') != 'owner':
        return jsonify({"status": "error", "message": "Doar Owner-ul poate promova admini!"}), 403

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET role = 'admin' WHERE id = %s", (target_user_id,))
        conn.commit()
        return jsonify({"status": "success", "message": "Utilizator promovat la Admin!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()
        

@app.route('/api/current_user_role')
def get_current_user_role():
    return jsonify({
        "role": session.get('role', 'guest'),
        "username": session.get('username')
    })
@app.route('/api/get_current_session')
def get_current_session():
    return jsonify({
        "logged_in": 'id' in session,
        "role": session.get('role', 'guest')
    })


@app.route('/produse_btn')
def produse_btn():
    conn = get_db_connection()
    if not conn: 
        return "Eroare la baza de date!"
    
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    query_products = """
        SELECT p.id, p.name, p.sku, p.price, p.stock_min, c.name as categorie_nume,
        (COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
         COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0)) as stock
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        ORDER BY p.id DESC;
    """
    cur.execute(query_products)
    all_products = cur.fetchall()
    
    cur.execute("SELECT id, name FROM categories ORDER BY name ASC;")
    all_categories = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('produse.html', products=all_products, categories=all_categories)


@app.route('/api/produse/categorie/<int:cat_id>')
def produse_per_categorie(cat_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    query = """
        SELECT 
            p.sku, 
            p.name, 
            p.price, 
            (COALESCE((SELECT SUM(quantity) FROM stock_entries WHERE product_id = p.id), 0) - 
             COALESCE((SELECT SUM(quantity) FROM stock_exits WHERE product_id = p.id), 0)) as stock
        FROM products p
        WHERE p.category_id = %s
        ORDER BY p.name ASC;
    """
    cur.execute(query, (cat_id,))
    produse = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(produse)

@app.route('/api/categorii/add', methods=['POST'])
def add_category():
    data = request.get_json()
    name = data.get('name')

    if not name:
        return jsonify({"success": False, "message": "Numele este obligatoriu"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("INSERT INTO categories (name) VALUES (%s) RETURNING id", (name,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()
        
@app.route('/api/categorii/delete/<int:cat_id>', methods=['DELETE'])
@roles_required('admin', 'owner')
def delete_category(cat_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("DELETE FROM products WHERE category_id = %s", (cat_id,))
        
        cur.execute("DELETE FROM categories WHERE id = %s", (cat_id,))
        
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/receptii/add', methods=['POST'])
@roles_required('admin', 'owner')
def add_reception():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        pret_total = float(data['cantitate']) * float(data['pret_produs'])
        
        query = """
            INSERT INTO receptii (nume_companie, nume_produs, cantitate, pret_produs, pret_total, email_firma, adresa_firma)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cur.execute(query, (
            data['nume_companie'],
            data['nume_produs'],
            data['cantitate'],
            data['pret_produs'],
            pret_total,
            data['email_firma'],
            data['adresa_firma']
        ))
        
        conn.commit()
        return jsonify({"success": True, "message": "Recepție salvată cu succes!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()
        
@app.route('/api/receptii/list', methods=['GET'])
def get_receptions():

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cur.execute("SELECT * FROM receptii ORDER BY id DESC")

        receptii = cur.fetchall()

        return jsonify({"success": True, "data": receptii})

    except Exception as e:

        return jsonify({"success": False, "message": str(e)}), 500

    finally:

        cur.close()
        conn.close()

@app.route('/api/receptii/grafic-date', methods=['GET'])
def get_chart_data():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        query = """
            SELECT nume_companie, SUM(pret_total) as total 
            FROM receptii 
            GROUP BY nume_companie 
            ORDER BY total DESC
        """
        cur.execute(query)
        date_grafic = cur.fetchall()
        return jsonify({"success": True, "data": date_grafic})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/intrari')
def intrari_dashboard():
    conn = get_db_connection()  
    if not conn:
        return "Eroare la conexiunea cu baza de date!"
    
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        now = datetime.now()
        luna_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            luna_end = now.replace(year=now.year+1, month=1, day=1, hour=0, minute=0, second=0)
        else:
            luna_end = now.replace(month=now.month+1, day=1, hour=0, minute=0, second=0)

        cur.execute("""
            SELECT COUNT(*) as total_intrari
            FROM receptii
            WHERE creat_la >= %s AND creat_la < %s
        """, (luna_start, luna_end))
        total_intrari = cur.fetchone()['total_intrari'] or 0

        cur.execute("""
            SELECT COALESCE(SUM(pret_total),0) as valoare_achizitii
            FROM receptii
            WHERE creat_la >= %s AND creat_la < %s
        """, (luna_start, luna_end))
        valoare_achizitii = cur.fetchone()['valoare_achizitii'] or 0

        cur.execute("""
            SELECT nume_companie, SUM(pret_total) as total
            FROM receptii
            WHERE creat_la >= %s AND creat_la < %s
            GROUP BY nume_companie
            ORDER BY total DESC
            LIMIT 1
        """, (luna_start, luna_end))
        top_furnizor_row = cur.fetchone()
        top_furnizor = top_furnizor_row['nume_companie'] if top_furnizor_row else "N/A"

        return render_template('intrari.html',
                               total_intrari=total_intrari,
                               valoare_achizitii=valoare_achizitii,
                               top_furnizor=top_furnizor)

    except Exception as e:
        print(f"Eroare Intrari Dashboard: {e}")
        return f"A intervenit o eroare la procesarea datelor: {e}"
    
    finally:
        cur.close()
        conn.close()

@app.route('/api/iesiri/add', methods=['POST'])
@roles_required('admin', 'owner')
def add_iesire():
    data = request.json
    
    if not data or 'receptie_id' not in data or 'cantitate' not in data:
        return jsonify({"success": False, "message": "Date incomplete!"})

    receptie_id = data['receptie_id']
    try:
        cantitate_de_scazut = int(data['cantitate'])
        if cantitate_de_scazut <= 0:
            return jsonify({"success": False, "message": "Cantitatea trebuie să fie mai mare decât 0!"})
    except ValueError:
        return jsonify({"success": False, "message": "Cantitate invalidă!"})

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT cantitate, pret_produs, nume_companie, nume_produs 
            FROM receptii 
            WHERE id = %s
        """, (receptie_id,))
        receptie = cur.fetchone()

        if not receptie:
            return jsonify({"success": False, "message": "Eroare: Lotul (Recepția) nu a fost găsit!"})
        
        stoc_actual = int(receptie['cantitate'])
        pret_unitar = float(receptie['pret_produs'])

        if stoc_actual < cantitate_de_scazut:
            return jsonify({"success": False, "message": f"Stoc insuficient! Disponibil: {stoc_actual}"})

        valoare_tranzactie_calculata = cantitate_de_scazut * pret_unitar

        noua_cantitate = stoc_actual - cantitate_de_scazut
        nou_pret_total = noua_cantitate * pret_unitar

        cur.execute("""
            UPDATE receptii 
            SET cantitate = %s, pret_total = %s 
            WHERE id = %s
        """, (noua_cantitate, nou_pret_total, receptie_id))

        cur.execute("""
            INSERT INTO iesiri (receptie_id, nume_companie, nume_produs, cantitate_iesita, valoare_tranzactie, data_iesire)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (
            receptie_id, 
            receptie['nume_companie'], 
            receptie['nume_produs'], 
            cantitate_de_scazut,
            valoare_tranzactie_calculata
        ))

        conn.commit()
        return jsonify({
            "success": True, 
            "message": "Ieșire înregistrată! Stocul a fost actualizat și valoarea a fost calculată."
        })

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"success": False, "message": f"Eroare server: {str(e)}"})
    finally:
        cur.close()
        conn.close()


@app.route('/intrari')
def intrari():
    return render_template('intrari.html')

@app.route('/api/iesiri/top-produse', methods=['GET'])
def get_top_produse_iesiri():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        query = """
            SELECT 
                nume_companie,
                SUM(valoare_tranzactie) AS total_valoare
            FROM iesiri
            GROUP BY nume_companie
            ORDER BY total_valoare DESC
        """

        cur.execute(query)
        data = cur.fetchall()

        return jsonify({
            "success": True,
            "data": data
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
            "data": []
        }), 500

    finally:
        cur.close()
        conn.close()

@app.route('/iesiri')
def iesiri():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT id, nume_companie, nume_produs, cantitate 
            FROM receptii 
            WHERE cantitate > 0 
            ORDER BY nume_companie ASC, id DESC
        """)
        receptii_active = cur.fetchall()

        cur.execute("""
            SELECT id, nume_produs, nume_companie, cantitate_iesita, receptie_id,
                   TO_CHAR(data_iesire, 'DD.MM.YYYY') as data,
                   TO_CHAR(data_iesire, 'HH24:MI') as ora
            FROM iesiri 
            ORDER BY data_iesire DESC
        """)
        iesiri_list = cur.fetchall()


        cur.execute("""
            SELECT SUM(cantitate_iesita) as total_unitati 
            FROM iesiri 
            WHERE data_iesire::date = CURRENT_DATE
        """)
        res_flux = cur.fetchone()
        flux_azi = res_flux['total_unitati'] if res_flux['total_unitati'] else 0

        cur.execute("""
            SELECT SUM(i.cantitate_iesita * r.pret_produs) as total_valoare
            FROM iesiri i
            JOIN receptii r ON i.receptie_id = r.id
            WHERE i.data_iesire::date = CURRENT_DATE
        """)
        res_valoare = cur.fetchone()
        valoare_azi = res_valoare['total_valoare'] if res_valoare['total_valoare'] else 0

        cur.execute("""
            SELECT nume_companie, SUM(cantitate_iesita) as total_volum
            FROM iesiri 
            GROUP BY nume_companie 
            ORDER BY total_volum DESC 
            LIMIT 1
        """)
        res_top = cur.fetchone()
        
        top_companie_final = res_top['nume_companie'] if res_top else "Fără livrări"
        
        return render_template('iesiri.html', 
                               receptii_active=receptii_active, 
                               iesiri=iesiri_list, 
                               flux=flux_azi,
                               valoare_livrata=valoare_azi,
                               top_companie=top_companie_final)
                               
    except Exception as e:
        print(f"Eroare SQL: {e}")
        return f"Eroare la încărcarea paginii: {str(e)}"
    finally:
        if cur: cur.close()
        if conn: conn.close()


@app.route('/api/v1/internal/inventory-event-ledger')
def get_inventory_ledger():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT id, product_id, product_name, type, 
                   old_system_stock, new_system_stock, 
                   old_faptic_stock, new_faptic_stock, 
                   created_at 
            FROM inventory_history 
            ORDER BY created_at DESC 
            LIMIT 100
        """)
        history = cur.fetchall()
        
        for item in history:
            if item['created_at']:
                item['created_at'] = item['created_at'].strftime('%Y-%m-%dT%H:%M:%S')
                
        return jsonify(history)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/iesiri/list')
def get_iesiri_json():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT id, nume_produs, nume_companie, cantitate_iesita, receptie_id,
                   TO_CHAR(data_iesire, 'DD.MM.YYYY') as data,
                   TO_CHAR(data_iesire, 'HH24:MI') as ora
            FROM iesiri 
            ORDER BY data_iesire DESC
        """)
        iesiri = cur.fetchall()
        return jsonify({"success": True, "data": iesiri})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
    finally:
        cur.close()
        conn.close()


@app.route('/api/stats/stock-discrepancy')
def get_stock_discrepancy():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    query = """
        SELECT 
            name, 
            COALESCE(last_system_stock, 0) as sistem, 
            COALESCE(last_faptic_value, 0) as faptic,
            (COALESCE(last_system_stock, 0) - COALESCE(last_faptic_value, 0)) as lipsa_unitati
        FROM products
        WHERE last_system_stock > last_faptic_value
        ORDER BY lipsa_unitati DESC
        LIMIT 10;
    """
    
    try:
        cur.execute(query)
        rows = cur.fetchall()
        return jsonify(rows)
    except Exception as e:
        print(f"Eroare Grafic: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/stats/top-performanta-mix')
def get_top_performanta_mix():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT 
                p.name, 
                SUM(ABS(COALESCE(h.new_faptic_stock, 0) - COALESCE(h.old_faptic_stock, 0))) as unitati_miscate,
                p.price,
                (SUM(ABS(COALESCE(h.new_faptic_stock, 0) - COALESCE(h.old_faptic_stock, 0))) * p.price) as scor_performanta
            FROM products p
            LEFT JOIN inventory_history h ON p.id = h.product_id
            WHERE p.price > 0 
              -- Putem lăsa filtrul de timp mai larg sau să-l scoatem de tot pentru a popula diagrama
              AND (h.created_at >= NOW() - INTERVAL '1 year' OR h.created_at IS NULL)
            GROUP BY p.id, p.name, p.price
            HAVING (SUM(ABS(COALESCE(h.new_faptic_stock, 0) - COALESCE(h.old_faptic_stock, 0))) * p.price) > 0
            ORDER BY scor_performanta DESC
            LIMIT 8  -- 8 elemente arată excelent pe un Polar Chart
        """)
        
        top_mix = cur.fetchall()
        
        if len(top_mix) < 3:
            cur.execute("""
                SELECT name, (faptic_stock * price) as scor_performanta 
                FROM products 
                WHERE faptic_stock > 0
                ORDER BY scor_performanta DESC 
                LIMIT 8
            """)
            top_mix = cur.fetchall()

        labels = [item['name'] for item in top_mix]
        values = [float(item['scor_performanta']) for item in top_mix]
        
        return jsonify({
            "labels": labels,
            "values": values
        })
    except Exception as e:
        print(f"Eroare API Mix: {e}")
        return jsonify({"labels": ["Fără date"], "values": [0]}), 200
    finally:
        cur.close()
        conn.close()
        
 
@app.route('/api/stats/stock-verificare')
def get_stock_verificare():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT 
                name, 
                COALESCE(last_faptic_value, 0) as faptic, 
                COALESCE(last_system_stock, 0) as sistem,
                (COALESCE(last_system_stock, 0) - COALESCE(last_faptic_value, 0)) as diferenta
            FROM products 
            WHERE (COALESCE(last_system_stock, 0) - COALESCE(last_faptic_value, 0)) BETWEEN 1 AND 5
            ORDER BY updated_at DESC
            LIMIT 10
        """)
        data = cur.fetchall()
        return jsonify(data)
    except Exception as e:
        print(f"Eroare SQL Verificare: {e}")
        return jsonify([])
    finally:
        cur.close()
        conn.close()


@app.route('/api/product-delete/<int:id>', methods=['DELETE'])
@roles_required('admin', 'owner')
def delete_product(id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Conexiune DB eșuată"}), 500
        
    try:
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT name, sku, last_system_stock, last_faptic_value 
            FROM products WHERE id = %s
        """, (id,))
        product = cur.fetchone()
        
        if not product:
            return jsonify({"status": "error", "message": "Produsul nu a fost găsit"}), 404

        p_name = product['name'] if product['name'] else "Produs fără nume"
        p_sku = product['sku'] if product['sku'] else "Fără SKU"
        product_label = f"{p_name} [{p_sku}]"
        
        old_sys = product['last_system_stock'] if product['last_system_stock'] is not None else 0
        old_fap = product['last_faptic_value'] if product['last_faptic_value'] is not None else 0

        cur.execute("""
            INSERT INTO inventory_history 
            (product_id, product_name, type, old_system_stock, new_system_stock, old_faptic_stock, new_faptic_stock, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """, (id, product_label, 'STERGERE PRODUS', old_sys, 0, old_fap, 0))

        cur.execute("DELETE FROM stock_entries WHERE product_id = %s", (id,))
        cur.execute("DELETE FROM stock_exits WHERE product_id = %s", (id,))

        cur.execute("DELETE FROM products WHERE id = %s", (id,))
        
        conn.commit()
        return jsonify({"status": "success", "message": "Produs șters și înregistrat în jurnal"})
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"--- EROARE LA STERGERE: {str(e)} ---") 
        return jsonify({"status": "error", "message": str(e)}), 400
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
    
 