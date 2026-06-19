from datetime import datetime, timedelta
from db.database import Database


class SuggestionService:
    def __init__(self, db: Database):
        self.db = db

    def get_low_stock_high_demand_outlets(self, days=7, min_orders=5, min_ratio=1.5):
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        sql = '''
            SELECT 
                o.id as outlet_id,
                o.name as outlet_name,
                o.location_type,
                o.address,
                COUNT(DISTINCT d.id) as current_devices,
                SUM(CASE WHEN d.status = 'deployed' THEN 1 ELSE 0 END) as available,
                SUM(CASE WHEN d.status = 'in_use' THEN 1 ELSE 0 END) as in_use,
                COUNT(DISTINCT ro.id) as order_count,
                COALESCE(SUM(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as total_revenue
            FROM outlets o
            LEFT JOIN devices d ON d.outlet_id = o.id
            LEFT JOIN rental_orders ro ON ro.outlet_id = o.id
                AND DATE(ro.return_time) >= ?
            WHERE o.status = 1
            GROUP BY o.id, o.name, o.location_type, o.address
            HAVING order_count >= ? 
               AND (available + in_use) > 0
               AND CAST(order_count AS FLOAT) / (available + in_use) >= ?
            ORDER BY CAST(order_count AS FLOAT) / (available + in_use) DESC
        '''
        rows = self.db.query(sql, (start_date, min_orders, min_ratio))
        results = []
        for r in rows:
            total = r.get('current_devices') or 0
            if total > 0:
                suggestion_qty = max(5, int(r.get('order_count') or 0) // 2 - total + 1)
            else:
                suggestion_qty = max(10, int(r.get('order_count') or 0) // 2)
            results.append({
                **dict(r),
                'suggestion_type': 'low_stock_high_demand',
                'type_label': '⚠️ 低库存高需求',
                'suggested_quantity': max(5, suggestion_qty),
                'reason': f"近{days}天{r.get('order_count',0)}单，设备仅{total}台，供需比1:{round((r.get('order_count',0)/max(total,1)),1)}"
            })
        return results

    def get_idle_outlets(self, days=14, min_devices=5, max_orders_ratio=0.3):
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        sql = '''
            SELECT 
                o.id as outlet_id,
                o.name as outlet_name,
                o.location_type,
                o.address,
                COUNT(DISTINCT d.id) as current_devices,
                SUM(CASE WHEN d.status = 'deployed' THEN 1 ELSE 0 END) as available,
                SUM(CASE WHEN d.status = 'in_use' THEN 1 ELSE 0 END) as in_use,
                COUNT(DISTINCT ro.id) as order_count,
                COALESCE(SUM(CASE WHEN ro.status = 'completed' THEN ro.final_amount END), 0) as total_revenue,
                MIN(CASE WHEN d.status IN ('deployed','in_use') THEN d.last_return_time END) as oldest_idle_time
            FROM outlets o
            LEFT JOIN devices d ON d.outlet_id = o.id
            LEFT JOIN rental_orders ro ON ro.outlet_id = o.id
                AND DATE(ro.return_time) >= ?
            WHERE o.status = 1
            GROUP BY o.id, o.name, o.location_type, o.address
            HAVING (available + in_use) >= ?
               AND CAST(order_count AS FLOAT) / (available + in_use) <= ?
            ORDER BY (available + in_use) DESC
        '''
        rows = self.db.query(sql, (start_date, min_devices, max_orders_ratio))
        results = []
        for r in rows:
            recoverable = (r.get('available') or 0) // 2
            if recoverable > 0:
                results.append({
                    **dict(r),
                    'suggestion_type': 'idle',
                    'type_label': '📉 设备闲置',
                    'suggested_quantity': recoverable,
                    'reason': f"近{days}天仅{r.get('order_count',0)}单，设备{r.get('available',0)+r.get('in_use',0)}台闲置，建议回收{recoverable}台"
                })
        return results

    def get_high_fault_outlets(self, fault_ratio_threshold=0.15, min_devices=3):
        sql = '''
            SELECT 
                o.id as outlet_id,
                o.name as outlet_name,
                o.location_type,
                o.address,
                COUNT(DISTINCT d.id) as current_devices,
                SUM(CASE WHEN d.status = 'faulty' THEN 1 ELSE 0 END) as faulty_count,
                SUM(CASE WHEN d.status = 'deployed' THEN 1 ELSE 0 END) as available,
                SUM(CASE WHEN d.status = 'in_use' THEN 1 ELSE 0 END) as in_use
            FROM outlets o
            JOIN devices d ON d.outlet_id = o.id
            WHERE o.status = 1
            GROUP BY o.id, o.name, o.location_type, o.address
            HAVING current_devices >= ?
               AND CAST(faulty_count AS FLOAT) / current_devices >= ?
            ORDER BY CAST(faulty_count AS FLOAT) / current_devices DESC
        '''
        rows = self.db.query(sql, (min_devices, fault_ratio_threshold))
        results = []
        for r in rows:
            results.append({
                **dict(r),
                'suggestion_type': 'high_fault',
                'type_label': '🚨 故障占比高',
                'fault_ratio': round((r.get('faulty_count') or 0) / max(r.get('current_devices', 1), 1) * 100, 1),
                'suggested_quantity': r.get('faulty_count', 0),
                'reason': f"设备总数{r.get('current_devices',0)}台，故障{r.get('faulty_count',0)}台，占比{round((r.get('faulty_count',0)/max(r.get('current_devices',1),1)*100),1)}%"
            })
        return results

    def get_all_suggestions(self):
        return {
            'low_stock': self.get_low_stock_high_demand_outlets(),
            'idle': self.get_idle_outlets(),
            'high_fault': self.get_high_fault_outlets()
        }

    def generate_plan_draft_from_suggestions(self, suggestions, plan_name=None, operator=None):
        if not suggestions:
            return None

        outlet_targets = {}
        location_types = set()
        total_target = 0

        for s in suggestions:
            outlet_id = s.get('outlet_id')
            if not outlet_id:
                continue
            qty = s.get('suggested_quantity') or 0
            if s.get('suggestion_type') == 'low_stock_high_demand':
                outlet_targets[outlet_id] = outlet_targets.get(outlet_id, 0) + qty
                total_target += qty
                if s.get('location_type'):
                    location_types.add(s['location_type'])
            elif s.get('suggestion_type') == 'idle':
                pass
            elif s.get('suggestion_type') == 'high_fault':
                outlet_targets[outlet_id] = outlet_targets.get(outlet_id, 0) + qty
                total_target += qty
                if s.get('location_type'):
                    location_types.add(s['location_type'])

        if total_target <= 0:
            return None

        if not plan_name:
            ts = datetime.now().strftime('%m%d')
            plan_name = f"运营建议补货计划-{ts}"

        return {
            'plan_name': plan_name,
            'location_type': list(location_types)[0] if len(location_types) == 1 else '混合类型',
            'target_quantity': total_target,
            'outlet_targets': [(oid, qty) for oid, qty in outlet_targets.items() if qty > 0],
            'priority': 'high',
            'plan_date': datetime.now().strftime('%Y-%m-%d'),
            'operator': operator,
            'remark': '由运营建议自动生成，含补货和故障替换',
            'source_suggestions': suggestions
        }
