from datetime import datetime
import random
import string
from db.database import Database
from services.outbound_service import OutboundService
from services.batch_service import BatchService


class DeploymentPlanService:
    def __init__(self, db: Database):
        self.db = db
        self.outbound_service = OutboundService(db)
        self.batch_service = BatchService(db)

    def _generate_plan_no(self):
        date_str = datetime.now().strftime('%Y%m%d')
        random_str = ''.join(random.choices(string.ascii_uppercase, k=2))
        count = self.db.query_one(f"SELECT COUNT(*) as cnt FROM deployment_plans WHERE plan_no LIKE 'DP{date_str}%'")
        seq = str(count['cnt'] + 1).zfill(4)
        return f'DP{date_str}{random_str}{seq}'

    def create_plan(self, plan_name, location_type, target_quantity, outlet_targets,
                    priority='normal', plan_date=None, operator=None, remark=None):
        if plan_date is None:
            plan_date = datetime.now().strftime('%Y-%m-%d')
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        plan_no = self._generate_plan_no()

        conn = self.db.connect()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO deployment_plans 
                (plan_no, plan_name, location_type, target_quantity, priority, 
                 plan_date, status, operator, remark, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            ''', (plan_no, plan_name, location_type, target_quantity, priority,
                  plan_date, operator, remark, now, now))
            plan_id = cursor.lastrowid

            for target in outlet_targets:
                if len(target) == 3:
                    outlet_id, outlet_qty, task_type = target
                else:
                    outlet_id, outlet_qty = target
                    task_type = 'restock'
                cursor.execute('''
                    INSERT INTO plan_outlets 
                    (plan_id, outlet_id, target_quantity, completed_quantity, task_type)
                    VALUES (?, ?, ?, 0, ?)
                ''', (plan_id, outlet_id, outlet_qty, task_type))

            conn.commit()
            return plan_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()

    def get_all_plans(self):
        return self.db.query('''
            SELECT p.*,
                   (SELECT COUNT(*) FROM plan_outlets po WHERE po.plan_id = p.id) as outlet_count
            FROM deployment_plans p
            ORDER BY p.created_at DESC
        ''')

    def get_plan_by_id(self, plan_id):
        plan = self.db.query_one('''
            SELECT p.*
            FROM deployment_plans p
            WHERE p.id = ?
        ''', (plan_id,))
        if plan:
            plan['outlets'] = self.db.query('''
                SELECT po.*, o.name as outlet_name, o.address, o.location_type as outlet_location_type,
                       (po.target_quantity - po.completed_quantity) as remaining_quantity
                FROM plan_outlets po
                JOIN outlets o ON po.outlet_id = o.id
                WHERE po.plan_id = ?
                ORDER BY po.target_quantity DESC
            ''', (plan_id,))
            plan['restock_outlets'] = [o for o in plan['outlets'] if o.get('task_type') == 'restock']
            plan['recovery_outlets'] = [o for o in plan['outlets'] if o.get('task_type') == 'recovery']
            plan['replace_outlets'] = [o for o in plan['outlets'] if o.get('task_type') == 'replace']
            task_type_summary = {}
            for o in plan['outlets']:
                tt = o.get('task_type', 'restock')
                if tt not in task_type_summary:
                    task_type_summary[tt] = {'target_quantity': 0, 'completed_quantity': 0}
                task_type_summary[tt]['target_quantity'] += o['target_quantity']
                task_type_summary[tt]['completed_quantity'] += o['completed_quantity']
            plan['task_type_summary'] = task_type_summary
            plan['executions'] = self.db.query('''
                SELECT so.*, o.name as outlet_name, db.batch_no
                FROM split_outbound so
                JOIN outlets o ON so.outlet_id = o.id
                JOIN device_batches db ON so.batch_id = db.id
                WHERE so.plan_id = ?
                ORDER BY so.outbound_date DESC
            ''', (plan_id,))
        return plan

    def execute_plan_outlet(self, plan_id, plan_outlet_id, batch_id, quantity, operator=None, outbound_date=None, remark=None, task_type='restock'):
        conn = self.db.connect()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM plan_outlets WHERE id = ?", (plan_outlet_id,))
            po = cursor.fetchone()
            if not po:
                raise ValueError("计划网点不存在")

            remaining = po['target_quantity'] - po['completed_quantity']
            if quantity > remaining:
                raise ValueError(f"该网点目标剩余{remaining}个，请求出库{quantity}个")

            cursor.execute("SELECT * FROM deployment_plans WHERE id = ?", (plan_id,))
            plan = cursor.fetchone()
            if not plan:
                raise ValueError("投放计划不存在")
            if plan['status'] == 'completed':
                raise ValueError("计划已完成，无需执行")

            self.db.close()

            result = self.outbound_service.split_outbound(
                batch_id=batch_id,
                quantity=quantity,
                outlet_id=po['outlet_id'],
                operator=operator,
                outbound_date=outbound_date,
                remark=remark,
                task_type=task_type
            )

            conn = self.db.connect()
            cursor = conn.cursor()

            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute('''
                UPDATE split_outbound 
                SET plan_id = ?, plan_outlet_id = ?, task_type = ?
                WHERE id = ?
            ''', (plan_id, plan_outlet_id, task_type, result['outbound_id']))

            cursor.execute('''
                UPDATE plan_outlets 
                SET completed_quantity = completed_quantity + ?,
                    completed_quantity = CASE 
                        WHEN completed_quantity + ? > target_quantity THEN target_quantity 
                        ELSE completed_quantity + ? 
                    END
                WHERE id = ?
            ''', (quantity, quantity, quantity, plan_outlet_id))

            cursor.execute('''
                UPDATE deployment_plans 
                SET completed_quantity = (
                    SELECT COALESCE(SUM(completed_quantity), 0) FROM plan_outlets WHERE plan_id = ?
                ),
                updated_at = ?
                WHERE id = ?
            ''', (plan_id, now, plan_id))

            cursor.execute('''
                SELECT target_quantity, completed_quantity FROM deployment_plans WHERE id = ?
            ''', (plan_id,))
            updated_plan = cursor.fetchone()
            if updated_plan['completed_quantity'] >= updated_plan['target_quantity']:
                cursor.execute('''
                    UPDATE deployment_plans SET status = 'completed', updated_at = ? WHERE id = ?
                ''', (now, plan_id))
            else:
                cursor.execute('''
                    UPDATE deployment_plans SET status = 'in_progress', updated_at = ? WHERE id = ?
                ''', (now, plan_id))

            conn.commit()
            return result
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()

    def get_plans_by_location_type(self, location_type):
        return self.db.query('''
            SELECT * FROM deployment_plans
            WHERE location_type = ?
            ORDER BY created_at DESC
        ''', (location_type,))

    def get_pending_quantity_by_location(self, location_type):
        rows = self.db.query('''
            SELECT 
                p.location_type,
                p.id as plan_id,
                p.plan_no,
                p.plan_name,
                po.id as plan_outlet_id,
                po.outlet_id,
                po.task_type,
                o.name as outlet_name,
                (po.target_quantity - po.completed_quantity) as remaining
            FROM deployment_plans p
            JOIN plan_outlets po ON po.plan_id = p.id
            JOIN outlets o ON o.id = po.outlet_id
            WHERE p.location_type = ? AND p.status IN ('pending', 'in_progress')
              AND (po.target_quantity - po.completed_quantity) > 0
            ORDER BY remaining DESC
        ''', (location_type,))
        return rows

    def update_plan_status(self, plan_id, status):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.db.execute('''
            UPDATE deployment_plans SET status = ?, updated_at = ? WHERE id = ?
        ''', (status, now, plan_id))

    def delete_plan(self, plan_id):
        conn = self.db.connect()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT COUNT(*) as cnt FROM split_outbound WHERE plan_id = ?
            ''', (plan_id,))
            if cursor.fetchone()['cnt'] > 0:
                raise ValueError("计划已有出库执行，无法删除")

            cursor.execute("DELETE FROM plan_outlets WHERE plan_id = ?", (plan_id,))
            cursor.execute("DELETE FROM deployment_plans WHERE id = ?", (plan_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.db.close()
