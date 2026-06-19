from datetime import datetime
import random
import string
from db.database import Database


class OutboundService:
    def __init__(self, db: Database):
        self.db = db

    def _generate_outbound_no(self):
        date_str = datetime.now().strftime('%Y%m%d')
        random_str = ''.join(random.choices(string.ascii_uppercase, k=2))
        count = self.db.query_one(f"SELECT COUNT(*) as cnt FROM split_outbound WHERE outbound_no LIKE 'OB{date_str}%'")
        seq = str(count['cnt'] + 1).zfill(4)
        return f'OB{date_str}{random_str}{seq}'

    def get_all_outbounds(self):
        return self.db.query('''
            SELECT so.*, 
                   db.batch_no,
                   o.name as outlet_name,
                   o.location_type
            FROM split_outbound so
            JOIN device_batches db ON so.batch_id = db.id
            JOIN outlets o ON so.outlet_id = o.id
            ORDER BY so.created_at DESC
        ''')

    def get_outbound_by_id(self, outbound_id):
        outbound = self.db.query_one('''
            SELECT so.*, 
                   db.batch_no,
                   o.name as outlet_name,
                   o.address as outlet_address
            FROM split_outbound so
            JOIN device_batches db ON so.batch_id = db.id
            JOIN outlets o ON so.outlet_id = o.id
            WHERE so.id = ?
        ''', (outbound_id,))

        if outbound:
            outbound['devices'] = self.db.query('''
                SELECT d.*
                FROM devices d
                WHERE d.split_outbound_id = ?
                ORDER BY d.device_no
            ''', (outbound_id,))

        return outbound

    def split_outbound(self, batch_id, quantity, outlet_id, operator=None, outbound_date=None, remark=None):
        if outbound_date is None:
            outbound_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        outbound_no = self._generate_outbound_no()

        conn = self.db.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM device_batches WHERE id = ?", (batch_id,))
            batch = cursor.fetchone()
            if not batch:
                raise ValueError("批次不存在")

            if batch['remaining_quantity'] < quantity:
                raise ValueError(f"批次剩余数量不足，剩余{batch['remaining_quantity']}个，请求出库{quantity}个")

            cursor.execute('''
                SELECT * FROM devices 
                WHERE batch_id = ? AND status = 'in_stock'
                ORDER BY device_no LIMIT ?
            ''', (batch_id, quantity))
            devices = cursor.fetchall()

            if len(devices) < quantity:
                raise ValueError("可用设备数量不足")

            cursor.execute('''
                INSERT INTO split_outbound 
                (batch_id, outbound_no, quantity, outlet_id, operator, outbound_date, remark, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (batch_id, outbound_no, quantity, outlet_id, operator, outbound_date, remark, now))

            outbound_id = cursor.lastrowid

            device_ids = []
            for device in devices:
                cursor.execute('''
                    UPDATE devices 
                    SET split_outbound_id = ?, 
                        outlet_id = ?, 
                        status = 'deployed',
                        updated_at = ?
                    WHERE id = ?
                ''', (outbound_id, outlet_id, now, device['id']))
                device_ids.append(device['id'])

            new_remaining = batch['remaining_quantity'] - quantity
            cursor.execute('''
                UPDATE device_batches 
                SET remaining_quantity = ?, updated_at = ?
                WHERE id = ?
            ''', (new_remaining, now, batch_id))

            conn.commit()

            return {
                'outbound_id': outbound_id,
                'outbound_no': outbound_no,
                'device_ids': device_ids
            }
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()

    def get_outlet_distribution(self):
        return self.db.query('''
            SELECT o.id, o.name, o.location_type, o.address,
                   COUNT(DISTINCT so.batch_id) as batch_count,
                   COUNT(DISTINCT d.id) as total_devices,
                   SUM(CASE WHEN d.status = 'deployed' THEN 1 ELSE 0 END) as deployed,
                   SUM(CASE WHEN d.status = 'in_use' THEN 1 ELSE 0 END) as in_use,
                   SUM(CASE WHEN d.status = 'faulty' THEN 1 ELSE 0 END) as faulty
            FROM outlets o
            LEFT JOIN devices d ON d.outlet_id = o.id
            LEFT JOIN split_outbound so ON d.split_outbound_id = so.id
            WHERE o.status = 1
            GROUP BY o.id, o.name, o.location_type, o.address
            ORDER BY total_devices DESC
        ''')

    def get_batch_outbound_history(self, batch_id):
        return self.db.query('''
            SELECT so.*,
                   o.name as outlet_name,
                   o.location_type,
                   (SELECT COUNT(*) FROM devices d WHERE d.split_outbound_id = so.id) as device_count
            FROM split_outbound so
            JOIN outlets o ON so.outlet_id = o.id
            WHERE so.batch_id = ?
            ORDER BY so.outbound_date DESC
        ''', (batch_id,))

    def get_outlet_devices(self, outlet_id):
        return self.db.query('''
            SELECT d.*, 
                   db.batch_no,
                   so.outbound_no,
                   so.outbound_date
            FROM devices d
            JOIN device_batches db ON d.batch_id = db.id
            LEFT JOIN split_outbound so ON d.split_outbound_id = so.id
            WHERE d.outlet_id = ?
            ORDER BY d.device_no
        ''', (outlet_id,))

    def get_device_flow_tracking(self, batch_id):
        return self.db.query('''
            SELECT 
                db.batch_no,
                db.total_quantity,
                db.remaining_quantity,
                so.id as outbound_id,
                so.outbound_no,
                so.quantity as outbound_quantity,
                so.outbound_date,
                o.name as outlet_name,
                o.location_type,
                d.device_no,
                d.status as device_status
            FROM device_batches db
            LEFT JOIN split_outbound so ON db.id = so.batch_id
            LEFT JOIN outlets o ON so.outlet_id = o.id
            LEFT JOIN devices d ON d.split_outbound_id = so.id
            WHERE db.id = ?
            ORDER BY so.outbound_date, d.device_no
        ''', (batch_id,))

    def get_distribution_stats(self):
        return self.db.query('''
            SELECT 
                o.location_type,
                COUNT(DISTINCT o.id) as outlet_count,
                COUNT(DISTINCT d.id) as device_count,
                SUM(CASE WHEN d.status = 'deployed' THEN 1 ELSE 0 END) as deployed,
                SUM(CASE WHEN d.status = 'in_use' THEN 1 ELSE 0 END) as in_use
            FROM outlets o
            LEFT JOIN devices d ON d.outlet_id = o.id
            WHERE o.status = 1
            GROUP BY o.location_type
            ORDER BY device_count DESC
        ''')

    def cancel_outbound(self, outbound_id):
        conn = self.db.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM split_outbound WHERE id = ?", (outbound_id,))
            outbound = cursor.fetchone()
            if not outbound:
                raise ValueError("出库记录不存在")

            cursor.execute("SELECT * FROM device_batches WHERE id = ?", (outbound['batch_id'],))
            batch = cursor.fetchone()
            if not batch:
                raise ValueError("关联批次不存在")

            cursor.execute('''
                SELECT * FROM devices 
                WHERE split_outbound_id = ? AND status = 'faulty'
            ''', (outbound_id,))
            faulty_devices = cursor.fetchall()
            if faulty_devices:
                raise ValueError("该出库存在故障设备，无法撤销")

            cursor.execute('''
                SELECT * FROM devices 
                WHERE split_outbound_id = ? AND status = 'in_use'
            ''', (outbound_id,))
            in_use_devices = cursor.fetchall()
            if in_use_devices:
                raise ValueError("该出库存在正在使用的设备，无法撤销")

            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute('''
                UPDATE devices 
                SET split_outbound_id = NULL, 
                    outlet_id = NULL, 
                    status = 'in_stock',
                    updated_at = ?
                WHERE split_outbound_id = ?
            ''', (now, outbound_id))

            new_remaining = batch['remaining_quantity'] + outbound['quantity']
            cursor.execute('''
                UPDATE device_batches 
                SET remaining_quantity = ?, updated_at = ?
                WHERE id = ?
            ''', (new_remaining, now, batch['id']))

            cursor.execute("DELETE FROM split_outbound WHERE id = ?", (outbound_id,))

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()
