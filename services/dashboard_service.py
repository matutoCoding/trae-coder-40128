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
        order_having = ""
        order_params = []
        if start_date:
            order_having += " AND DATE(ro.return_time) >= ?"
            order_params.append(start_date)
        if end_date:
            order_having += " AND DATE(ro.return_time) <= ?"
            order_params.append(end_date)
        if location_type:
            order_having += " AND o2.location_type = ?"
            order_params.append(location_type)

        order_where = ""
        if order_having:
            order_where = "WHERE " + order_having[5:]

        outlet_filter_params = []
        outlet_filter = "WHERE o.status = 1"
        if location_type:
            outlet_filter += " AND o.location_type = ?"
            outlet_filter_params.append(location_type)

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
                {order_where}
                GROUP BY ro.outlet_id
            ) ord ON ord.outlet_id = o.id
            {outlet_filter}
            ORDER BY total_revenue DESC
        '''
        all_params = order_params + outlet_filter_params
        return self.db.query(sql, all_params if all_params else None)

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

    def get_trend_data(self, start_date=None, end_date=None, location_type=None, outlet_id=None, granularity='daily'):
        order_where = "WHERE ro.status = 'completed'"
        order_params = []
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

        device_where = "WHERE 1=1"
        device_params = []
        if location_type:
            device_where += " AND o.location_type = ?"
            device_params.append(location_type)
        if outlet_id:
            device_where += " AND d.outlet_id = ?"
            device_params.append(outlet_id)

        if granularity == 'weekly':
            group_expr = "strftime('%Y-W%W', ro.return_time)"
            select_expr = f"{group_expr} as stat_week, DATE(MIN(ro.return_time)) as stat_date"
        else:
            group_expr = "DATE(ro.return_time)"
            select_expr = "DATE(ro.return_time) as stat_date"

        order_sql = f'''
            SELECT {select_expr},
                   COUNT(*) as orders,
                   COALESCE(SUM(ro.final_amount), 0) as revenue
            FROM rental_orders ro
            JOIN outlets o ON ro.outlet_id = o.id
            {order_where}
            GROUP BY {group_expr}
            ORDER BY stat_date
        '''
        order_rows = self.db.query(order_sql, order_params if order_params else None)

        date_where_params = []
        date_where = ""
        if start_date:
            date_where += " AND d.event_date >= ?"
            date_where_params.append(start_date)
        if end_date:
            date_where += " AND d.event_date <= ?"
            date_where_params.append(end_date)

        rent_filter = ""
        rent_params = []
        if location_type:
            rent_filter += " AND o.location_type = ?"
            rent_params.append(location_type)
        if outlet_id:
            rent_filter += " AND ro.outlet_id = ?"
            rent_params.append(outlet_id)

        maint_filter = ""
        maint_params = []
        if location_type:
            maint_filter += " AND o.location_type = ?"
            maint_params.append(location_type)
        if outlet_id:
            maint_filter += " AND d.outlet_id = ?"
            maint_params.append(outlet_id)

        if granularity == 'weekly':
            date_group = "strftime('%Y-W%W', d.event_date)"
            date_select = f"{date_group} as stat_period, MAX(d.event_date) as period_end_date"
            order_group = "strftime('%Y-W%W', ro.return_time)"
            maint_group = "strftime('%Y-W%W', dm.maintenance_date)"
        else:
            date_group = "DATE(d.event_date)"
            date_select = f"{date_group} as stat_period, DATE(d.event_date) as period_end_date"
            order_group = "DATE(ro.return_time)"
            maint_group = "DATE(dm.maintenance_date)"

        all_params = date_where_params + rent_params + rent_params + maint_params + maint_params

        if granularity == 'weekly':
            borrow_group = "strftime('%Y-W%W', ro.borrow_time)"
            return_group = "strftime('%Y-W%W', ro.return_time)"
            maint_group_expr = "strftime('%Y-W%W', dm.maintenance_date)"
        else:
            borrow_group = "DATE(ro.borrow_time)"
            return_group = "DATE(ro.return_time)"
            maint_group_expr = "DATE(dm.maintenance_date)"

        history_sql = f'''
            WITH RECURSIVE date_range AS (
                SELECT 
                    COALESCE(
                        (SELECT MIN(DATE(borrow_time)) FROM rental_orders WHERE DATE(borrow_time) IS NOT NULL),
                        (SELECT MIN(DATE(return_time)) FROM rental_orders WHERE DATE(return_time) IS NOT NULL),
                        (SELECT MIN(DATE(maintenance_date)) FROM device_maintenance WHERE DATE(maintenance_date) IS NOT NULL),
                        DATE('now', '-30 days')
                    ) as event_date
                UNION ALL
                SELECT DATE(event_date, '+1 day')
                FROM date_range
                WHERE event_date <= COALESCE(
                    (SELECT MAX(DATE(return_time)) FROM rental_orders WHERE DATE(return_time) IS NOT NULL),
                    (SELECT MAX(DATE(borrow_time)) FROM rental_orders WHERE DATE(borrow_time) IS NOT NULL),
                    (SELECT MAX(DATE(maintenance_date)) FROM device_maintenance WHERE DATE(maintenance_date) IS NOT NULL),
                    DATE('now')
                )
            ),
            date_grouped AS (
                SELECT {date_select}
                FROM date_range d
                WHERE 1=1 {date_where}
                GROUP BY {date_group}
                ORDER BY period_end_date
            ),
            all_rent_events AS (
                SELECT 
                    {borrow_group} as stat_period,
                    1 as is_borrow,
                    0 as is_return
                FROM rental_orders ro
                JOIN outlets o ON ro.outlet_id = o.id
                WHERE ro.borrow_time IS NOT NULL {rent_filter}
                UNION ALL
                SELECT 
                    {return_group} as stat_period,
                    0 as is_borrow,
                    1 as is_return
                FROM rental_orders ro
                JOIN outlets o ON ro.outlet_id = o.id
                WHERE ro.return_time IS NOT NULL {rent_filter}
            ),
            daily_change AS (
                SELECT 
                    stat_period,
                    SUM(is_borrow) as borrows,
                    SUM(is_return) as returns,
                    SUM(is_borrow) - SUM(is_return) as delta_in_use
                FROM all_rent_events
                GROUP BY stat_period
            ),
            all_maint_events AS (
                SELECT 
                    {maint_group_expr} as stat_period,
                    1 as is_lock,
                    0 as is_unlock
                FROM device_maintenance dm
                JOIN devices d ON dm.device_id = d.id
                JOIN outlets o ON d.outlet_id = o.id
                WHERE dm.maintenance_type = 'lock' {maint_filter}
                UNION ALL
                SELECT 
                    {maint_group_expr} as stat_period,
                    0 as is_lock,
                    1 as is_unlock
                FROM device_maintenance dm
                JOIN devices d ON dm.device_id = d.id
                JOIN outlets o ON d.outlet_id = o.id
                WHERE dm.maintenance_type = 'unlock' {maint_filter}
            ),
            daily_fault AS (
                SELECT 
                    stat_period,
                    SUM(is_lock) as locks,
                    SUM(is_unlock) as unlocks,
                    SUM(is_lock) - SUM(is_unlock) as delta_fault
                FROM all_maint_events
                GROUP BY stat_period
            ),
            period_changes AS (
                SELECT 
                    dg.stat_period,
                    dg.period_end_date,
                    COALESCE(dc.delta_in_use, 0) as delta_in_use,
                    COALESCE(df.delta_fault, 0) as delta_fault
                FROM date_grouped dg
                LEFT JOIN daily_change dc ON dc.stat_period = dg.stat_period
                LEFT JOIN daily_fault df ON df.stat_period = dg.stat_period
            )
            SELECT 
                stat_period,
                period_end_date,
                SUM(delta_in_use) OVER (ORDER BY period_end_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) as cumulative_in_use,
                SUM(delta_fault) OVER (ORDER BY period_end_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) as cumulative_fault
            FROM period_changes
            ORDER BY period_end_date
        '''

        history_rows = self.db.query(history_sql, all_params if all_params else None)
        has_history = False
        in_use_map = {}
        faulty_map = {}

        if history_rows:
            total_delta_in_use = sum(abs(r.get('cumulative_in_use', 0)) for r in history_rows)
            total_delta_fault = sum(abs(r.get('cumulative_fault', 0)) for r in history_rows)
            if total_delta_in_use > 0 or total_delta_fault > 0:
                has_history = True
                for r in history_rows:
                    period = r['stat_period']
                    in_use_map[period] = max(0, r.get('cumulative_in_use', 0) or 0)
                    faulty_map[period] = max(0, r.get('cumulative_fault', 0) or 0)

        if not has_history:
            current_in_use_sql = f'''
                SELECT COUNT(*) as in_use_devices
                FROM devices d
                JOIN outlets o ON d.outlet_id = o.id
                {device_where}
                  AND d.status = 'in_use'
            '''
            current_in_use_row = self.db.query_one(current_in_use_sql, device_params if device_params else None)
            current_in_use = current_in_use_row.get('in_use_devices', 0) if current_in_use_row else 0

            faulty_sql = f'''
                SELECT COUNT(*) as faulty_devices
                FROM devices d
                JOIN outlets o ON d.outlet_id = o.id
                {device_where}
                  AND d.status = 'faulty'
            '''
            faulty_row = self.db.query_one(faulty_sql, device_params if device_params else None)
            current_faulty = faulty_row.get('faulty_devices', 0) if faulty_row else 0

            result = []
            for row in order_rows:
                item = {
                    'stat_date': row['stat_date'],
                    'orders': row['orders'],
                    'revenue': row['revenue'],
                    'in_use_devices': current_in_use,
                    'faulty_devices': current_faulty,
                }
                if granularity == 'weekly':
                    item['stat_week'] = row['stat_week']
                result.append(item)
            return result

        result = []
        for row in order_rows:
            if granularity == 'weekly':
                period = row['stat_week']
            else:
                period = row['stat_date']

            item = {
                'stat_date': row['stat_date'],
                'orders': row['orders'],
                'revenue': row['revenue'],
                'in_use_devices': in_use_map.get(period, 0),
                'faulty_devices': faulty_map.get(period, 0),
            }
            if granularity == 'weekly':
                item['stat_week'] = row['stat_week']
            result.append(item)
        return result

    def get_outlet_turnover(self, outlet_id, start_date=None, end_date=None):
        borrow_where = "WHERE ro.outlet_id = ?"
        borrow_params = [outlet_id]
        if start_date:
            borrow_where += " AND DATE(ro.borrow_time) >= ?"
            borrow_params.append(start_date)
        if end_date:
            borrow_where += " AND DATE(ro.borrow_time) <= ?"
            borrow_params.append(end_date)

        total_devices_row = self.db.query_one(
            "SELECT COUNT(*) as total_devices FROM devices WHERE outlet_id = ?",
            (outlet_id,)
        )
        total_devices = total_devices_row.get('total_devices', 0) if total_devices_row else 0

        borrow_sql = f'''
            SELECT COUNT(*) as total_borrows
            FROM rental_orders ro
            {borrow_where}
        '''
        borrow_row = self.db.query_one(borrow_sql, borrow_params)
        total_borrows = borrow_row.get('total_borrows', 0) if borrow_row else 0

        return_where = borrow_where + " AND ro.status = 'completed'"
        return_sql = f'''
            SELECT COUNT(*) as total_returns,
                   COALESCE(AVG(ro.duration_minutes), 0) as avg_borrow_duration
            FROM rental_orders ro
            {return_where}
        '''
        return_row = self.db.query_one(return_sql, borrow_params)
        total_returns = return_row.get('total_returns', 0) if return_row else 0
        avg_borrow_duration = return_row.get('avg_borrow_duration', 0) if return_row else 0

        turnover_rate = round(total_borrows / total_devices, 2) if total_devices > 0 else 0

        return {
            'total_devices': total_devices,
            'total_borrows': total_borrows,
            'total_returns': total_returns,
            'avg_borrow_duration': avg_borrow_duration,
            'turnover_rate': turnover_rate,
        }

    def get_reconciliation_data(self, start_date=None, end_date=None, location_type=None):
        report_where = "WHERE o.status = 1"
        report_params = []
        if location_type:
            report_where += " AND o.location_type = ?"
            report_params.append(location_type)

        date_filter = ""
        if start_date:
            date_filter += " AND DATE(ro.return_time) >= ?"
            report_params.append(start_date)
        if end_date:
            date_filter += " AND DATE(ro.return_time) <= ?"
            report_params.append(end_date)

        completed_params = []
        completed_date_filter = ""
        if location_type:
            completed_date_filter += " AND o.location_type = ?"
            completed_params.append(location_type)
        if start_date:
            completed_date_filter += " AND DATE(ro.return_time) >= ?"
            completed_params.append(start_date)
        if end_date:
            completed_date_filter += " AND DATE(ro.return_time) <= ?"
            completed_params.append(end_date)

        page_summary_sql = f'''
            SELECT 
                COUNT(ro.id) as total_orders,
                COALESCE(SUM(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as total_revenue
            FROM outlets o
            LEFT JOIN rental_orders ro ON ro.outlet_id = o.id
                {date_filter}
            {report_where}
            HAVING COUNT(ro.id) > 0
        '''
        page_summary_rows = self.db.query(page_summary_sql, report_params if report_params else None)
        page_summary = {
            'total_orders': sum(r['total_orders'] for r in page_summary_rows),
            'total_revenue': sum(r['total_revenue'] for r in page_summary_rows),
        }

        completed_summary_sql = f'''
            SELECT 
                COUNT(*) as total_orders,
                COALESCE(SUM(ro.final_amount), 0) as total_revenue
            FROM rental_orders ro
            JOIN outlets o ON ro.outlet_id = o.id
            WHERE ro.status = 'completed'
            {completed_date_filter}
        '''
        completed_summary = self.db.query_one(completed_summary_sql, completed_params if completed_params else None) or {}
        completed_only = {
            'total_orders': completed_summary.get('total_orders', 0) or 0,
            'total_revenue': completed_summary.get('total_revenue', 0) or 0,
        }

        outlet_report_params = []
        outlet_report_where = "WHERE o.status = 1"
        if location_type:
            outlet_report_where += " AND o.location_type = ?"
            outlet_report_params.append(location_type)

        outlet_date_params = []
        outlet_date_filter = ""
        if start_date:
            outlet_date_filter += " AND DATE(ro.return_time) >= ?"
            outlet_date_params.append(start_date)
        if end_date:
            outlet_date_filter += " AND DATE(ro.return_time) <= ?"
            outlet_date_params.append(end_date)

        outlet_sql = f'''
            SELECT 
                o.id as outlet_id,
                o.name as outlet_name,
                COUNT(ro.id) as report_orders,
                COALESCE(SUM(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as report_revenue,
                COUNT(CASE WHEN ro.status = 'completed' THEN 1 END) as completed_orders,
                COALESCE(SUM(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as completed_revenue
            FROM outlets o
            LEFT JOIN rental_orders ro ON ro.outlet_id = o.id
                {outlet_date_filter}
            {outlet_report_where}
            GROUP BY o.id, o.name
            HAVING COUNT(ro.id) > 0
            ORDER BY report_revenue DESC
        '''
        all_params = outlet_date_params + outlet_report_params
        outlet_rows = self.db.query(outlet_sql, all_params if all_params else None)

        outlet_details = []
        for row in outlet_rows:
            report_orders = row['report_orders'] or 0
            completed_orders = row['completed_orders'] or 0
            report_revenue = row['report_revenue'] or 0
            completed_revenue = row['completed_revenue'] or 0
            outlet_details.append({
                'outlet_id': row['outlet_id'],
                'outlet_name': row['outlet_name'],
                'report_orders': report_orders,
                'report_revenue': report_revenue,
                'completed_orders': completed_orders,
                'completed_revenue': completed_revenue,
                'diff_orders': report_orders - completed_orders,
                'diff_revenue': round(report_revenue - completed_revenue, 2),
            })

        return {
            'page_summary': page_summary,
            'completed_only': completed_only,
            'outlet_details': outlet_details,
        }
