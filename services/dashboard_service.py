from datetime import datetime
from db.database import Database


class DashboardService:
    def __init__(self, db: Database):
        self.db = db

    def get_overview_stats(self, start_date=None, end_date=None, location_type=None, outlet_id=None):
        device_params = []
        device_where = "WHERE 1=1"
        if location_type:
            device_where += " AND o.location_type = ?"
            device_params.append(location_type)
        if outlet_id:
            device_where += " AND d.outlet_id = ?"
            device_params.append(outlet_id)

        order_params = []
        order_where = "WHERE ro.status = 'completed'"
        if location_type:
            order_where += " AND o.location_type = ?"
            order_params.append(location_type)
        if outlet_id:
            order_where += " AND ro.outlet_id = ?"
            order_params.append(outlet_id)
        if start_date:
            order_where += " AND DATE(ro.return_time) >= ?"
            order_params.append(start_date)
        if end_date:
            order_where += " AND DATE(ro.return_time) <= ?"
            order_params.append(end_date)

        active_params = []
        active_where = "WHERE ro.status = 'active'"
        if location_type:
            active_where += " AND o.location_type = ?"
            active_params.append(location_type)
        if outlet_id:
            active_where += " AND ro.outlet_id = ?"
            active_params.append(outlet_id)

        device_sql = f'''
            SELECT 
                COUNT(*) as total_devices,
                SUM(CASE WHEN d.status = 'in_stock' THEN 1 ELSE 0 END) as in_stock,
                SUM(CASE WHEN d.status = 'deployed' THEN 1 ELSE 0 END) as deployed,
                SUM(CASE WHEN d.status = 'in_use' THEN 1 ELSE 0 END) as in_use,
                SUM(CASE WHEN d.status = 'faulty' THEN 1 ELSE 0 END) as faulty
            FROM devices d
            LEFT JOIN outlets o ON d.outlet_id = o.id
            {device_where}
        '''
        device_stats = self.db.query_one(device_sql, device_params if device_params else None) or {}

        order_sql = f'''
            SELECT 
                COUNT(*) as total_orders,
                COALESCE(SUM(ro.final_amount), 0) as total_revenue,
                COALESCE(AVG(ro.final_amount), 0) as avg_amount,
                COALESCE(AVG(ro.duration_minutes), 0) as avg_duration
            FROM rental_orders ro
            JOIN outlets o ON ro.outlet_id = o.id
            {order_where}
        '''
        order_stats = self.db.query_one(order_sql, order_params if order_params else None) or {}

        active_sql = f'''
            SELECT COUNT(*) as active_orders
            FROM rental_orders ro
            JOIN outlets o ON ro.outlet_id = o.id
            {active_where}
        '''
        active_stats = self.db.query_one(active_sql, active_params if active_params else None) or {}

        result = {
            'total_devices': device_stats.get('total_devices', 0) or 0,
            'in_stock': device_stats.get('in_stock', 0) or 0,
            'deployed': device_stats.get('deployed', 0) or 0,
            'in_use': device_stats.get('in_use', 0) or 0,
            'faulty': device_stats.get('faulty', 0) or 0,
            'total_orders': order_stats.get('total_orders', 0) or 0,
            'active_orders': active_stats.get('active_orders', 0) or 0,
            'total_revenue': order_stats.get('total_revenue', 0) or 0,
            'avg_amount': order_stats.get('avg_amount', 0) or 0,
            'avg_duration': order_stats.get('avg_duration', 0) or 0,
        }
        result['deployed_in_use'] = result['deployed'] + result['in_use']
        return result

    def get_outlet_stats(self, start_date=None, end_date=None, location_type=None):
        outlet_where = "WHERE o.status = 1"
        order_where = "WHERE 1=1"
        device_where = "WHERE 1=1"
        params = []

        if location_type:
            outlet_where += " AND o.location_type = ?"
            order_where += " AND o.location_type = ?"
            device_where += " AND o.location_type = ?"
            params.append(location_type)

        order_params = list(params)
        device_params = list(params)

        if start_date:
            order_where += " AND DATE(ro.return_time) >= ?"
            order_params.append(start_date)
        if end_date:
            order_where += " AND DATE(ro.return_time) <= ?"
            order_params.append(end_date)

        sql = f'''
            SELECT 
                o.id as outlet_id,
                o.name as outlet_name,
                o.location_type,
                o.address,
                COALESCE(dev.total_devices, 0) as total_devices,
                COALESCE(dev.deployed, 0) as deployed,
                COALESCE(dev.in_use, 0) as in_use,
                COALESCE(dev.faulty, 0) as faulty,
                COALESCE(ord.total_orders, 0) as total_orders,
                COALESCE(ord.total_revenue, 0) as total_revenue,
                COALESCE(ord.avg_duration, 0) as avg_duration
            FROM outlets o
            LEFT JOIN (
                SELECT 
                    outlet_id,
                    COUNT(*) as total_devices,
                    SUM(CASE WHEN status = 'deployed' THEN 1 ELSE 0 END) as deployed,
                    SUM(CASE WHEN status = 'in_use' THEN 1 ELSE 0 END) as in_use,
                    SUM(CASE WHEN status = 'faulty' THEN 1 ELSE 0 END) as faulty
                FROM devices
                GROUP BY outlet_id
            ) dev ON dev.outlet_id = o.id
            LEFT JOIN (
                SELECT 
                    ro.outlet_id,
                    COUNT(*) as total_orders,
                    COALESCE(SUM(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as total_revenue,
                    COALESCE(AVG(CASE WHEN ro.status = 'completed' THEN ro.duration_minutes END), 0) as avg_duration
                FROM rental_orders ro
                JOIN outlets o2 ON ro.outlet_id = o2.id
                {order_where.replace("WHERE 1=1 AND", "WHERE") if order_where != "WHERE 1=1" else ""}
                GROUP BY ro.outlet_id
            ) ord ON ord.outlet_id = o.id
            {outlet_where.replace("WHERE ", "AND ") if outlet_where != "WHERE o.status = 1" else "WHERE o.status = 1"}
            ORDER BY total_revenue DESC
        '''
        return self.db.query(sql, order_params if order_params else None)

    def get_outlet_devices_detail(self, outlet_id):
        return self.db.query('''
            SELECT d.*, db.batch_no,
                   so.outbound_no, so.outbound_date,
                   o.name as outlet_name
            FROM devices d
            JOIN device_batches db ON d.batch_id = db.id
            LEFT JOIN split_outbound so ON d.split_outbound_id = so.id
            LEFT JOIN outlets o ON d.outlet_id = o.id
            WHERE d.outlet_id = ?
            ORDER BY d.status, d.device_no
        ''', (outlet_id,))

    def get_outlet_orders_detail(self, outlet_id, start_date=None, end_date=None):
        sql = '''
            SELECT ro.*,
                   d.device_no,
                   o.name as outlet_name,
                   br.name as rule_name
            FROM rental_orders ro
            JOIN devices d ON ro.device_id = d.id
            JOIN outlets o ON ro.outlet_id = o.id
            JOIN billing_rules br ON ro.billing_rule_id = br.id
            WHERE ro.outlet_id = ?
        '''
        params = [outlet_id]
        if start_date:
            sql += " AND DATE(ro.return_time) >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND DATE(ro.return_time) <= ?"
            params.append(end_date)
        sql += " ORDER BY ro.return_time DESC"
        return self.db.query(sql, params)

    def get_location_types(self):
        rows = self.db.query('''
            SELECT DISTINCT location_type FROM outlets 
            WHERE status = 1 AND location_type IS NOT NULL AND location_type != ''
            ORDER BY location_type
        ''')
        return [r['location_type'] for r in rows]

    def get_all_outlets(self, location_type=None):
        sql = "SELECT * FROM outlets WHERE status = 1"
        params = []
        if location_type:
            sql += " AND location_type = ?"
            params.append(location_type)
        sql += " ORDER BY name"
        return self.db.query(sql, params if params else None)
