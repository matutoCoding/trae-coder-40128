from datetime import datetime
import random
import string
from db.database import Database
from services.billing_service import BillingService


class RentalService:
    def __init__(self, db: Database):
        self.db = db
        self.billing_service = BillingService(db)

    def _generate_order_no(self):
        date_str = datetime.now().strftime('%Y%m%d')
        random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return f'RO{date_str}{random_str}'

    def _generate_bill_no(self):
        date_str = datetime.now().strftime('%Y%m%d')
        random_str = ''.join(random.choices(string.ascii_uppercase, k=2))
        count = self.db.query_one(f"SELECT COUNT(*) as cnt FROM bills WHERE bill_no LIKE 'BL{date_str}%'")
        seq = str(count['cnt'] + 1).zfill(4)
        return f'BL{date_str}{random_str}{seq}'

    def borrow_device(self, device_id, outlet_id, borrow_time=None):
        if borrow_time is None:
            borrow_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        order_no = self._generate_order_no()

        conn = self.db.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            device = cursor.fetchone()
            if not device:
                raise ValueError("设备不存在")

            if device['status'] != 'deployed':
                raise ValueError(f"设备状态为{device['status']}，无法租借")

            active_rule = self.billing_service.get_active_rule()
            if not active_rule:
                raise ValueError("没有可用的计费规则")

            cursor.execute('''
                INSERT INTO rental_orders 
                (order_no, device_id, outlet_id, borrow_time, billing_rule_id, 
                 start_price, hourly_price, max_price, final_amount, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'active', ?, ?)
            ''', (order_no, device_id, outlet_id, borrow_time, active_rule['id'],
                  active_rule['start_price'], active_rule['price_per_hour'],
                  active_rule['max_price_per_day'], now, now))

            cursor.execute('''
                UPDATE devices 
                SET status = 'in_use', last_borrow_time = ?, updated_at = ?
                WHERE id = ?
            ''', (borrow_time, now, device_id))

            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()

    def return_device(self, device_id, return_time=None):
        if return_time is None:
            return_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = self.db.connect()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT * FROM rental_orders 
                WHERE device_id = ? AND status = 'active'
                ORDER BY borrow_time DESC LIMIT 1
            ''', (device_id,))
            order = cursor.fetchone()
            if not order:
                raise ValueError("该设备没有进行中的租借订单")

            fee_result = self.billing_service.calculate_rental_fee(
                order['borrow_time'], return_time, order['billing_rule_id']
            )

            duration_minutes = fee_result['duration_minutes']

            cursor.execute('''
                UPDATE rental_orders 
                SET return_time = ?, 
                    duration_minutes = ?,
                    calculated_amount = ?,
                    final_amount = ?,
                    status = 'completed',
                    updated_at = ?
                WHERE id = ?
            ''', (return_time, duration_minutes,
                  fee_result['calculated_amount'], fee_result['final_amount'],
                  now, order['id']))

            cursor.execute('''
                UPDATE devices 
                SET status = 'deployed', last_return_time = ?, updated_at = ?
                WHERE id = ?
            ''', (return_time, now, device_id))

            conn.commit()
            return {
                'order_id': order['id'],
                'fee': fee_result
            }
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()

    def get_available_devices_for_rent(self, outlet_id):
        return self.db.query('''
            SELECT d.*, db.batch_no
            FROM devices d
            JOIN device_batches db ON d.batch_id = db.id
            WHERE d.outlet_id = ? AND d.status = 'deployed'
            ORDER BY d.device_no
        ''', (outlet_id,))

    def get_active_orders(self):
        return self.db.query('''
            SELECT ro.*, 
                   d.device_no,
                   o.name as outlet_name,
                   br.name as rule_name
            FROM rental_orders ro
            JOIN devices d ON ro.device_id = d.id
            JOIN outlets o ON ro.outlet_id = o.id
            JOIN billing_rules br ON ro.billing_rule_id = br.id
            WHERE ro.status = 'active'
            ORDER BY ro.borrow_time DESC
        ''')

    def get_completed_orders(self, start_date=None, end_date=None):
        sql = '''
            SELECT ro.*, 
                   d.device_no,
                   o.name as outlet_name,
                   br.name as rule_name
            FROM rental_orders ro
            JOIN devices d ON ro.device_id = d.id
            JOIN outlets o ON ro.outlet_id = o.id
            JOIN billing_rules br ON ro.billing_rule_id = br.id
            WHERE ro.status = 'completed'
        '''
        params = []
        if start_date:
            sql += " AND DATE(ro.return_time) >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND DATE(ro.return_time) <= ?"
            params.append(end_date)
        sql += " ORDER BY ro.return_time DESC"
        return self.db.query(sql, params if params else None)

    def get_order_by_id(self, order_id):
        return self.db.query_one('''
            SELECT ro.*, 
                   d.device_no,
                   o.name as outlet_name,
                   br.name as rule_name
            FROM rental_orders ro
            JOIN devices d ON ro.device_id = d.id
            JOIN outlets o ON ro.outlet_id = o.id
            JOIN billing_rules br ON ro.billing_rule_id = br.id
            WHERE ro.id = ?
        ''', (order_id,))

    def generate_daily_bill(self, bill_date=None):
        if bill_date is None:
            bill_date = datetime.now().strftime('%Y-%m-%d')

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = self.db.connect()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT * FROM bills WHERE DATE(bill_date) = ?
            ''', (bill_date,))
            if cursor.fetchone():
                raise ValueError(f"{bill_date} 的账单已存在")

            cursor.execute('''
                SELECT ro.*, 
                       d.device_no,
                       o.name as outlet_name
                FROM rental_orders ro
                JOIN devices d ON ro.device_id = d.id
                JOIN outlets o ON ro.outlet_id = o.id
                WHERE ro.status = 'completed' 
                  AND DATE(ro.return_time) = ?
                  AND ro.id NOT IN (SELECT order_id FROM bill_items)
                ORDER BY ro.return_time
            ''', (bill_date,))
            orders = cursor.fetchall()

            if not orders:
                return None

            bill_no = self._generate_bill_no()
            total_amount = sum(order['final_amount'] for order in orders)
            order_count = len(orders)

            cursor.execute('''
                INSERT INTO bills 
                (bill_no, bill_date, order_count, total_amount, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'unsettled', ?, ?)
            ''', (bill_no, bill_date, order_count, total_amount, now, now))

            bill_id = cursor.lastrowid

            for order in orders:
                cursor.execute('''
                    INSERT INTO bill_items 
                    (bill_id, order_id, device_no, outlet_name, borrow_time, 
                     return_time, duration_minutes, amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (bill_id, order['id'], order['device_no'], order['outlet_name'],
                      order['borrow_time'], order['return_time'],
                      order['duration_minutes'], order['final_amount']))

            conn.commit()
            return {
                'bill_id': bill_id,
                'bill_no': bill_no,
                'order_count': order_count,
                'total_amount': total_amount
            }
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()

    def get_all_bills(self):
        return self.db.query('''
            SELECT b.*,
                   (SELECT COUNT(*) FROM bill_items bi WHERE bi.bill_id = b.id) as item_count
            FROM bills b
            ORDER BY b.bill_date DESC
        ''')

    def get_bill_by_id(self, bill_id):
        bill = self.db.query_one('''
            SELECT b.*
            FROM bills b
            WHERE b.id = ?
        ''', (bill_id,))

        if bill:
            bill['items'] = self.db.query('''
                SELECT bi.*
                FROM bill_items bi
                WHERE bi.bill_id = ?
                ORDER BY bi.id
            ''', (bill_id,))

        return bill

    def get_faulty_devices(self):
        return self.db.query('''
            SELECT d.*, 
                   db.batch_no,
                   o.name as outlet_name,
                   (SELECT description FROM device_maintenance dm 
                    WHERE dm.device_id = d.id 
                    ORDER BY dm.created_at DESC LIMIT 1) as last_maintenance
            FROM devices d
            JOIN device_batches db ON d.batch_id = db.id
            LEFT JOIN outlets o ON d.outlet_id = o.id
            WHERE d.status = 'faulty'
            ORDER BY d.updated_at DESC
        ''')

    def mark_device_faulty(self, device_id, description=None, operator=None):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = self.db.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            device = cursor.fetchone()
            if not device:
                raise ValueError("设备不存在")

            if device['status'] == 'in_use':
                raise ValueError("设备正在使用中，无法标记为故障")

            if device['status'] == 'faulty':
                raise ValueError("设备已标记为故障")

            cursor.execute('''
                UPDATE devices 
                SET status = 'faulty', updated_at = ?
                WHERE id = ?
            ''', (now, device_id))

            cursor.execute('''
                INSERT INTO device_maintenance 
                (device_id, maintenance_type, description, operator, maintenance_date, created_at)
                VALUES (?, 'lock', ?, ?, ?, ?)
            ''', (device_id, description, operator, now, now))

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()

    def unlock_device(self, device_id, description=None, operator=None):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = self.db.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            device = cursor.fetchone()
            if not device:
                raise ValueError("设备不存在")

            if device['status'] != 'faulty':
                raise ValueError("设备状态不是故障，无法解锁")

            new_status = 'in_stock' if device['outlet_id'] is None else 'deployed'

            cursor.execute('''
                UPDATE devices 
                SET status = ?, updated_at = ?
                WHERE id = ?
            ''', (new_status, now, device_id))

            cursor.execute('''
                INSERT INTO device_maintenance 
                (device_id, maintenance_type, description, operator, maintenance_date, created_at)
                VALUES (?, 'unlock', ?, ?, ?, ?)
            ''', (device_id, description, operator, now, now))

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()

    def get_rental_summary(self, start_date=None, end_date=None):
        sql = '''
            SELECT 
                COUNT(*) as total_orders,
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_orders,
                COUNT(CASE WHEN status = 'active' THEN 1 END) as active_orders,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN final_amount END), 0) as total_revenue,
                COALESCE(AVG(CASE WHEN status = 'completed' THEN final_amount END), 0) as avg_amount,
                COALESCE(AVG(CASE WHEN status = 'completed' THEN duration_minutes END), 0) as avg_duration
            FROM rental_orders
            WHERE 1=1
        '''
        params = []
        if start_date:
            sql += " AND DATE(created_at) >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND DATE(created_at) <= ?"
            params.append(end_date)

        return self.db.query_one(sql, params if params else None)

    def get_revenue_report_by_outlet(self, start_date, end_date):
        sql = '''
            SELECT 
                o.id as outlet_id,
                o.name as outlet_name,
                o.location_type,
                COUNT(ro.id) as order_count,
                COUNT(CASE WHEN ro.status = 'completed' THEN 1 END) as completed_count,
                COUNT(CASE WHEN ro.status = 'active' THEN 1 END) as active_count,
                COALESCE(SUM(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as total_revenue,
                COALESCE(AVG(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as avg_amount,
                COALESCE(AVG(CASE WHEN ro.status = 'completed' THEN ro.duration_minutes END), 0) as avg_duration,
                COALESCE(SUM(CASE WHEN ro.status = 'completed' THEN ro.duration_minutes END), 0) as total_duration_minutes
            FROM outlets o
            LEFT JOIN rental_orders ro ON ro.outlet_id = o.id
                AND DATE(ro.return_time) >= ? 
                AND DATE(ro.return_time) <= ?
            WHERE o.status = 1
            GROUP BY o.id, o.name, o.location_type
            HAVING COUNT(ro.id) > 0
            ORDER BY total_revenue DESC
        '''
        return self.db.query(sql, (start_date, end_date))

    def get_revenue_report_summary(self, start_date, end_date):
        sql = '''
            SELECT 
                COUNT(DISTINCT ro.outlet_id) as outlet_count,
                COUNT(ro.id) as total_orders,
                COUNT(CASE WHEN ro.status = 'completed' THEN 1 END) as completed_orders,
                COUNT(CASE WHEN ro.status = 'active' THEN 1 END) as active_orders,
                COALESCE(SUM(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as total_revenue,
                COALESCE(AVG(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as avg_amount,
                COALESCE(AVG(CASE WHEN ro.status = 'completed' THEN ro.duration_minutes END), 0) as avg_duration
            FROM rental_orders ro
            WHERE DATE(ro.return_time) >= ? 
              AND DATE(ro.return_time) <= ?
        '''
        return self.db.query_one(sql, (start_date, end_date))

    def get_outlet_orders_detail(self, outlet_id, start_date, end_date):
        return self.db.query('''
            SELECT ro.*,
                   d.device_no,
                   o.name as outlet_name,
                   br.name as rule_name
            FROM rental_orders ro
            JOIN devices d ON ro.device_id = d.id
            JOIN outlets o ON ro.outlet_id = o.id
            JOIN billing_rules br ON ro.billing_rule_id = br.id
            WHERE ro.outlet_id = ?
              AND DATE(ro.return_time) >= ? 
              AND DATE(ro.return_time) <= ?
              AND ro.status = 'completed'
            ORDER BY ro.return_time DESC
        ''', (outlet_id, start_date, end_date))

    def get_revenue_by_location_type(self, start_date, end_date):
        return self.db.query('''
            SELECT 
                o.location_type,
                COUNT(DISTINCT o.id) as outlet_count,
                COUNT(ro.id) as order_count,
                COALESCE(SUM(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as total_revenue,
                COALESCE(AVG(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as avg_amount
            FROM outlets o
            LEFT JOIN rental_orders ro ON ro.outlet_id = o.id
                AND DATE(ro.return_time) >= ? 
                AND DATE(ro.return_time) <= ?
            WHERE o.status = 1
            GROUP BY o.location_type
            ORDER BY total_revenue DESC
        ''', (start_date, end_date))

    def get_daily_revenue_trend(self, start_date, end_date, outlet_id=None):
        sql = '''
            SELECT 
                DATE(ro.return_time) as stat_date,
                COUNT(ro.id) as order_count,
                COALESCE(SUM(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as revenue
            FROM rental_orders ro
            WHERE DATE(ro.return_time) >= ? 
              AND DATE(ro.return_time) <= ?
        '''
        params = [start_date, end_date]
        if outlet_id:
            sql += " AND ro.outlet_id = ?"
            params.append(outlet_id)
        sql += " GROUP BY DATE(ro.return_time) ORDER BY stat_date"
        return self.db.query(sql, params)
