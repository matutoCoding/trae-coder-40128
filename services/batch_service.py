from datetime import datetime
import random
import string
from db.database import Database


class BatchService:
    def __init__(self, db: Database):
        self.db = db

    def _generate_batch_no(self):
        date_str = datetime.now().strftime('%Y%m%d')
        random_str = ''.join(random.choices(string.ascii_uppercase, k=2))
        count = self.db.query_one(f"SELECT COUNT(*) as cnt FROM device_batches WHERE batch_no LIKE 'PB{date_str}%'")
        seq = str(count['cnt'] + 1).zfill(4)
        return f'PB{date_str}{random_str}{seq}'

    def _generate_device_no(self, batch_no, index):
        return f'{batch_no}-{str(index).zfill(4)}'

    def get_all_batches(self):
        return self.db.query('''
            SELECT b.*, 
                   (SELECT COUNT(*) FROM devices d WHERE d.batch_id = b.id) as device_count,
                   (SELECT COUNT(*) FROM devices d WHERE d.batch_id = b.id AND d.status = 'in_stock') as in_stock_count,
                   (SELECT COUNT(*) FROM devices d WHERE d.batch_id = b.id AND d.status = 'deployed') as deployed_count,
                   (SELECT COUNT(*) FROM devices d WHERE d.batch_id = b.id AND d.status = 'faulty') as faulty_count
            FROM device_batches b ORDER BY b.created_at DESC
        ''')

    def get_batch_by_id(self, batch_id):
        batch = self.db.query_one("SELECT * FROM device_batches WHERE id = ?", (batch_id,))
        if batch:
            batch['devices'] = self.db.query('''
                SELECT d.*, o.name as outlet_name
                FROM devices d
                LEFT JOIN outlets o ON d.outlet_id = o.id
                WHERE d.batch_id = ?
                ORDER BY d.device_no
            ''', (batch_id,))
        return batch

    def add_batch(self, total_quantity, model=None, purchase_date=None, supplier=None, unit_cost=None, remark=None):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        batch_no = self._generate_batch_no()

        conn = self.db.connect()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO device_batches 
                (batch_no, total_quantity, remaining_quantity, model, purchase_date, supplier, unit_cost, remark, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (batch_no, total_quantity, total_quantity, model, purchase_date, supplier, unit_cost, remark, now, now))

            batch_id = cursor.lastrowid

            for i in range(1, total_quantity + 1):
                device_no = self._generate_device_no(batch_no, i)
                cursor.execute('''
                    INSERT INTO devices (device_no, batch_id, status, created_at, updated_at)
                    VALUES (?, ?, 'in_stock', ?, ?)
                ''', (device_no, batch_id, now, now))

            conn.commit()
            return batch_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()

    def update_batch(self, batch_id, model=None, purchase_date=None, supplier=None, unit_cost=None, remark=None):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        fields = []
        values = []
        if model is not None:
            fields.append('model=?')
            values.append(model)
        if purchase_date is not None:
            fields.append('purchase_date=?')
            values.append(purchase_date)
        if supplier is not None:
            fields.append('supplier=?')
            values.append(supplier)
        if unit_cost is not None:
            fields.append('unit_cost=?')
            values.append(unit_cost)
        if remark is not None:
            fields.append('remark=?')
            values.append(remark)
        fields.append('updated_at=?')
        values.append(now)
        values.append(batch_id)

        sql = f"UPDATE device_batches SET {', '.join(fields)} WHERE id=?"
        self.db.execute(sql, values)

    def delete_batch(self, batch_id):
        batch = self.get_batch_by_id(batch_id)
        if batch and batch['remaining_quantity'] != batch['total_quantity']:
            raise ValueError("批次已有设备出库，无法删除")

        conn = self.db.connect()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM devices WHERE batch_id = ?", (batch_id,))
            cursor.execute("DELETE FROM device_batches WHERE id = ?", (batch_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()

    def get_available_devices(self, batch_id, count):
        return self.db.query('''
            SELECT * FROM devices 
            WHERE batch_id = ? AND status = 'in_stock'
            ORDER BY device_no LIMIT ?
        ''', (batch_id, count))

    def get_all_outlets(self):
        return self.db.query("SELECT * FROM outlets WHERE status = 1 ORDER BY name")

    def add_outlet(self, name, address=None, contact_person=None, phone=None, location_type=None):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return self.db.execute('''
            INSERT INTO outlets (name, address, contact_person, phone, location_type, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        ''', (name, address, contact_person, phone, location_type, now, now))

    def update_outlet(self, outlet_id, name, address=None, contact_person=None, phone=None, location_type=None, status=1):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.db.execute('''
            UPDATE outlets SET name=?, address=?, contact_person=?, phone=?, location_type=?, status=?, updated_at=?
            WHERE id=?
        ''', (name, address, contact_person, phone, location_type, status, now, outlet_id))

    def get_batch_distribution(self, batch_id):
        return self.db.query('''
            SELECT o.id, o.name, o.location_type,
                   COUNT(d.id) as device_count,
                   SUM(CASE WHEN d.status = 'deployed' THEN 1 ELSE 0 END) as deployed_count,
                   SUM(CASE WHEN d.status = 'in_use' THEN 1 ELSE 0 END) as in_use_count,
                   SUM(CASE WHEN d.status = 'faulty' THEN 1 ELSE 0 END) as faulty_count
            FROM outlets o
            LEFT JOIN devices d ON d.outlet_id = o.id AND d.batch_id = ?
            WHERE EXISTS (SELECT 1 FROM devices d2 WHERE d2.batch_id = ? AND d2.outlet_id = o.id)
            GROUP BY o.id, o.name, o.location_type
            ORDER BY device_count DESC
        ''', (batch_id, batch_id))

    def get_distribution_summary(self):
        return self.db.query('''
            SELECT 
                (SELECT COUNT(*) FROM device_batches) as total_batches,
                (SELECT SUM(total_quantity) FROM device_batches) as total_devices,
                (SELECT COUNT(*) FROM devices WHERE status = 'in_stock') as in_stock,
                (SELECT COUNT(*) FROM devices WHERE status = 'deployed') as deployed,
                (SELECT COUNT(*) FROM devices WHERE status = 'in_use') as in_use,
                (SELECT COUNT(*) FROM devices WHERE status = 'faulty') as faulty,
                (SELECT COUNT(*) FROM outlets WHERE status = 1) as active_outlets
        ''')[0]

    def get_batch_timeline(self, batch_id):
        events = []

        batch = self.get_batch_by_id(batch_id)
        if not batch:
            return events

        events.append({
            'type': '入库',
            'icon': '📥',
            'time': batch['created_at'],
            'title': f'批次入库 - {batch["batch_no"]}',
            'description': f'采购{batch["total_quantity"]}台，型号:{batch.get("model") or "未知"}，供应商:{batch.get("supplier") or "未知"}',
            'device_range': f'{batch["total_quantity"]}台'
        })

        outbounds = self.db.query('''
            SELECT so.*, o.name as outlet_name, o.location_type,
                   dp.plan_name, dp.plan_no
            FROM split_outbound so
            JOIN outlets o ON so.outlet_id = o.id
            LEFT JOIN deployment_plans dp ON so.plan_id = dp.id
            WHERE so.batch_id = ?
            ORDER BY so.outbound_date
        ''', (batch_id,))

        for ob in outbounds:
            plan_info = f'（计划:{ob["plan_no"]} - {ob["plan_name"]}）' if ob.get('plan_name') else ''
            events.append({
                'type': '出库',
                'icon': '🚚',
                'time': ob['outbound_date'],
                'title': f'拆分出库至{ob["outlet_name"]}',
                'description': f'出库{ob["quantity"]}台到{ob.get("location_type","")}网点{plan_info}，操作员:{ob.get("operator","未记录")}',
                'device_range': f'{ob["quantity"]}台'
            })

            devices = self.db.query('''
                SELECT d.* FROM devices d
                WHERE d.split_outbound_id = ?
                ORDER BY d.device_no
            ''', (ob['id'],))

            for device in devices:
                if device.get('last_borrow_time') or device.get('status') in ('in_use', 'deployed'):
                    orders = self.db.query('''
                        SELECT ro.*, o.name as outlet_name
                        FROM rental_orders ro
                        JOIN outlets o ON ro.outlet_id = o.id
                        WHERE ro.device_id = ?
                        ORDER BY ro.borrow_time
                    ''', (device['id'],))

                    for order in orders:
                        if order['status'] == 'active':
                            events.append({
                                'type': '租借',
                                'icon': '🔴',
                                'time': order['borrow_time'],
                                'title': f'设备{device["device_no"]}租借进行中',
                                'description': f'⏳ 在借中：{order.get("outlet_name","")}网点借出，暂未归还',
                                'device_range': device['device_no'],
                                'is_active': True
                            })
                        else:
                            duration = f'{order["duration_minutes"]}分钟' if order.get('duration_minutes') else '未归还'
                            amount = f'{order["final_amount"]:.2f}元' if order.get('final_amount') is not None else '计费中'
                            days = 0
                            if order.get('duration_minutes') and order.get('duration_minutes') > 0:
                                days = (order['duration_minutes'] - 1) // 1440 + 1
                            cap_info = f"（封顶{days}天）" if days > 1 else ""
                            events.append({
                                'type': '租借',
                                'icon': '🔋',
                                'time': order['borrow_time'],
                                'title': f'设备{device["device_no"]}租借已完成',
                                'description': f'{order.get("outlet_name","")}网点借出，时长{duration}，收费{amount}{cap_info}，归还于{order.get("return_time","")}',
                                'device_range': device['device_no'],
                                'is_active': False
                            })

                maintenance = self.db.query('''
                    SELECT dm.* FROM device_maintenance dm
                    WHERE dm.device_id = ?
                    ORDER BY dm.maintenance_date
                ''', (device['id'],))

                for m in maintenance:
                    action = '故障锁定' if m['maintenance_type'] == 'lock' else '解锁恢复'
                    icon = '⚠️' if m['maintenance_type'] == 'lock' else '✅'
                    events.append({
                        'type': '维护',
                        'icon': icon,
                        'time': m['maintenance_date'],
                        'title': f'设备{device["device_no"]}{action}',
                        'description': f'{m.get("description","无描述")}，操作员:{m.get("operator","未记录")}',
                        'device_range': device['device_no']
                    })

        events.sort(key=lambda x: x['time'])
        return events

    def get_batch_active_rentals(self, batch_id):
        return self.db.query('''
            SELECT ro.*,
                   d.device_no,
                   o.name as outlet_name,
                   o.location_type
            FROM rental_orders ro
            JOIN devices d ON ro.device_id = d.id
            JOIN outlets o ON ro.outlet_id = o.id
            WHERE d.batch_id = ? AND ro.status = 'active'
            ORDER BY ro.borrow_time DESC
        ''', (batch_id,))

    def get_device_full_timeline(self, device_no):
        events = []

        device = self.db.query_one('''
            SELECT d.*, db.batch_no, db.created_at as batch_created_at,
                   o.name as outlet_name, o.location_type,
                   so.outbound_no, so.outbound_date
            FROM devices d
            JOIN device_batches db ON d.batch_id = db.id
            LEFT JOIN split_outbound so ON d.split_outbound_id = so.id
            LEFT JOIN outlets o ON d.outlet_id = o.id
            WHERE d.device_no = ?
        ''', (device_no,))

        if not device:
            return []

        events.append({
            'type': '入库',
            'icon': '📥',
            'time': device['batch_created_at'],
            'title': f'批次入库 - {device["batch_no"]}',
            'description': f'设备{device_no}随批次入库'
        })

        if device.get('outbound_date'):
            events.append({
                'type': '出库',
                'icon': '🚚',
                'time': device['outbound_date'],
                'title': f'出库至{device.get("outlet_name","")}',
                'description': f'通过{device["outbound_no"]}投放至{device.get("location_type","")}网点'
            })

        orders = self.db.query('''
            SELECT ro.*, o.name as outlet_name
            FROM rental_orders ro
            JOIN outlets o ON ro.outlet_id = o.id
            WHERE ro.device_id = ?
            ORDER BY ro.borrow_time
        ''', (device['id'],))

        for order in orders:
            status = '进行中' if order['status'] == 'active' else '已完成'
            duration = f'{order["duration_minutes"]}分钟' if order.get('duration_minutes') else '-'
            amount = f'{order["final_amount"]:.2f}元' if order.get('final_amount') is not None else '-'
            events.append({
                'type': '租借',
                'icon': '🔋',
                'time': order['borrow_time'],
                'title': f'租借{status}',
                'description': f'{order.get("outlet_name","")}借出，时长{duration}，收费{amount}'
            })

        maintenance = self.db.query('''
            SELECT dm.* FROM device_maintenance dm
            WHERE dm.device_id = ?
            ORDER BY dm.maintenance_date
        ''', (device['id'],))

        for m in maintenance:
            action = '故障锁定下架' if m['maintenance_type'] == 'lock' else '解锁恢复使用'
            icon = '⚠️' if m['maintenance_type'] == 'lock' else '✅'
            events.append({
                'type': '维护',
                'icon': icon,
                'time': m['maintenance_date'],
                'title': action,
                'description': f'{m.get("description","无描述")}，操作员:{m.get("operator","未记录")}'
            })

        events.sort(key=lambda x: x['time'])
        return events
