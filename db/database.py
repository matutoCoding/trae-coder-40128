import sqlite3
import os
from datetime import datetime


class Database:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'power_bank.db')
        self.db_path = db_path
        self.conn = None

    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        return self.conn

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def init_database(self):
        conn = self.connect()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS billing_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                start_price REAL NOT NULL DEFAULT 0,
                free_minutes INTEGER NOT NULL DEFAULT 0,
                price_per_hour REAL NOT NULL DEFAULT 0,
                max_price_per_day REAL NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_no TEXT NOT NULL UNIQUE,
                total_quantity INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                model TEXT,
                purchase_date TEXT,
                supplier TEXT,
                unit_cost REAL,
                remark TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS outlets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT,
                contact_person TEXT,
                phone TEXT,
                location_type TEXT,
                status INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS split_outbound (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                outbound_no TEXT NOT NULL UNIQUE,
                quantity INTEGER NOT NULL,
                outlet_id INTEGER NOT NULL,
                device_status TEXT NOT NULL DEFAULT 'normal',
                operator TEXT,
                outbound_date TEXT NOT NULL,
                remark TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (batch_id) REFERENCES device_batches(id),
                FOREIGN KEY (outlet_id) REFERENCES outlets(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_no TEXT NOT NULL UNIQUE,
                batch_id INTEGER NOT NULL,
                split_outbound_id INTEGER,
                outlet_id INTEGER,
                status TEXT NOT NULL DEFAULT 'in_stock',
                last_borrow_time TEXT,
                last_return_time TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (batch_id) REFERENCES device_batches(id),
                FOREIGN KEY (split_outbound_id) REFERENCES split_outbound(id),
                FOREIGN KEY (outlet_id) REFERENCES outlets(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rental_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT NOT NULL UNIQUE,
                device_id INTEGER NOT NULL,
                outlet_id INTEGER NOT NULL,
                borrow_time TEXT NOT NULL,
                return_time TEXT,
                duration_minutes INTEGER,
                billing_rule_id INTEGER NOT NULL,
                start_price REAL,
                hourly_price REAL,
                max_price REAL,
                calculated_amount REAL,
                final_amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (device_id) REFERENCES devices(id),
                FOREIGN KEY (outlet_id) REFERENCES outlets(id),
                FOREIGN KEY (billing_rule_id) REFERENCES billing_rules(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_no TEXT NOT NULL UNIQUE,
                bill_date TEXT NOT NULL,
                order_count INTEGER NOT NULL DEFAULT 0,
                total_amount REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'unsettled',
                remark TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bill_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id INTEGER NOT NULL,
                order_id INTEGER NOT NULL,
                device_no TEXT,
                outlet_name TEXT,
                borrow_time TEXT,
                return_time TEXT,
                duration_minutes INTEGER,
                amount REAL NOT NULL,
                FOREIGN KEY (bill_id) REFERENCES bills(id),
                FOREIGN KEY (order_id) REFERENCES rental_orders(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_maintenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL,
                maintenance_type TEXT NOT NULL,
                description TEXT,
                operator TEXT,
                maintenance_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (device_id) REFERENCES devices(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deployment_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_no TEXT NOT NULL UNIQUE,
                plan_name TEXT NOT NULL,
                location_type TEXT NOT NULL,
                target_quantity INTEGER NOT NULL,
                completed_quantity INTEGER NOT NULL DEFAULT 0,
                priority TEXT DEFAULT 'normal',
                plan_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                operator TEXT,
                remark TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS plan_outlets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id INTEGER NOT NULL,
                outlet_id INTEGER NOT NULL,
                target_quantity INTEGER NOT NULL,
                completed_quantity INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (plan_id) REFERENCES deployment_plans(id),
                FOREIGN KEY (outlet_id) REFERENCES outlets(id)
            )
        ''')

        try:
            cursor.execute("ALTER TABLE split_outbound ADD COLUMN plan_id INTEGER REFERENCES deployment_plans(id)")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE split_outbound ADD COLUMN plan_outlet_id INTEGER REFERENCES plan_outlets(id)")
        except sqlite3.OperationalError:
            pass

        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM billing_rules WHERE is_active = 1")
        if cursor.fetchone()[0] == 0:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute('''
                INSERT INTO billing_rules 
                (name, start_price, free_minutes, price_per_hour, max_price_per_day, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', ('默认计费规则', 2.0, 5, 1.0, 10.0, 1, now, now))

        cursor.execute("SELECT COUNT(*) FROM outlets")
        if cursor.fetchone()[0] == 0:
            outlets = [
                ('高铁站店', '高铁站候车厅A区', '张三', '13800138001', '交通枢纽'),
                ('购物中心店', '万达广场1楼入口', '李四', '13800138002', '商业综合体'),
                ('写字楼店', '科技园A座大堂', '王五', '13800138003', '写字楼'),
                ('医院店', '人民医院门诊楼', '赵六', '13800138004', '医疗机构'),
                ('大学城店', '师范大学食堂旁', '孙七', '13800138005', '教育机构'),
            ]
            for outlet in outlets:
                cursor.execute('''
                    INSERT INTO outlets (name, address, contact_person, phone, location_type, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ''', (*outlet, now, now))

        conn.commit()
        self.close()

    def execute(self, sql, params=None):
        conn = self.connect()
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        conn.commit()
        last_id = cursor.lastrowid
        self.close()
        return last_id

    def query(self, sql, params=None):
        conn = self.connect()
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        rows = [dict(row) for row in cursor.fetchall()]
        self.close()
        return rows

    def query_one(self, sql, params=None):
        conn = self.connect()
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        row = cursor.fetchone()
        self.close()
        return dict(row) if row else None
