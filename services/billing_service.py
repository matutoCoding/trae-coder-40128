from datetime import datetime
from db.database import Database


class BillingService:
    def __init__(self, db: Database):
        self.db = db

    def get_active_rule(self):
        return self.db.query_one(
            "SELECT * FROM billing_rules WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        )

    def get_all_rules(self):
        return self.db.query("SELECT * FROM billing_rules ORDER BY id DESC")

    def add_rule(self, name, start_price, free_minutes, price_per_hour, max_price_per_day, is_active=False):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return self.db.execute('''
            INSERT INTO billing_rules 
            (name, start_price, free_minutes, price_per_hour, max_price_per_day, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, start_price, free_minutes, price_per_hour, max_price_per_day, 1 if is_active else 0, now, now))

    def update_rule(self, rule_id, name, start_price, free_minutes, price_per_hour, max_price_per_day):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.db.execute('''
            UPDATE billing_rules 
            SET name=?, start_price=?, free_minutes=?, price_per_hour=?, max_price_per_day=?, updated_at=?
            WHERE id=?
        ''', (name, start_price, free_minutes, price_per_hour, max_price_per_day, now, rule_id))

    def set_active_rule(self, rule_id):
        self.db.execute("UPDATE billing_rules SET is_active = 0")
        self.db.execute("UPDATE billing_rules SET is_active = 1 WHERE id = ?", (rule_id,))

    def delete_rule(self, rule_id):
        self.db.execute("DELETE FROM billing_rules WHERE id = ?", (rule_id,))

    def calculate_rental_fee(self, borrow_time, return_time, rule_id=None):
        if rule_id is None:
            rule = self.get_active_rule()
        else:
            rule = self.db.query_one("SELECT * FROM billing_rules WHERE id = ?", (rule_id,))

        if not rule:
            raise ValueError("No active billing rule found")

        start_price = rule['start_price']
        free_minutes = rule['free_minutes']
        price_per_hour = rule['price_per_hour']
        max_price_per_day = rule['max_price_per_day']

        if isinstance(borrow_time, str):
            borrow_time = datetime.strptime(borrow_time, '%Y-%m-%d %H:%M:%S')
        if isinstance(return_time, str):
            return_time = datetime.strptime(return_time, '%Y-%m-%d %H:%M:%S')

        duration_seconds = (return_time - borrow_time).total_seconds()
        duration_minutes = int(duration_seconds / 60)

        if duration_minutes <= 0:
            duration_minutes = 1

        billable_minutes = max(0, duration_minutes - free_minutes)

        if billable_minutes == 0:
            calculated_amount = 0.0
            final_amount = 0.0
        elif billable_minutes <= 60:
            calculated_amount = start_price
            final_amount = start_price
        else:
            billable_hours = billable_minutes / 60.0
            calculated_amount = start_price + (billable_hours - 1) * price_per_hour

            if max_price_per_day > 0:
                rental_days = (duration_minutes - 1) // 1440 + 1
                max_total = max_price_per_day * rental_days
                final_amount = min(calculated_amount, max_total)
            else:
                final_amount = calculated_amount

        final_amount = round(final_amount, 2)
        calculated_amount = round(calculated_amount, 2)

        rental_days = (duration_minutes - 1) // 1440 + 1 if duration_minutes > 0 else 1
        return {
            'duration_minutes': duration_minutes,
            'billable_minutes': billable_minutes,
            'rental_days': rental_days,
            'start_price': start_price,
            'price_per_hour': price_per_hour,
            'max_price_per_day': max_price_per_day,
            'calculated_amount': calculated_amount,
            'final_amount': final_amount,
            'rule_id': rule['id'],
            'rule_name': rule['name']
        }

    def simulate_fee(self, hours, rule_id=None):
        from datetime import timedelta
        borrow = datetime.now()
        return_time = borrow + timedelta(hours=hours)
        return self.calculate_rental_fee(borrow, return_time, rule_id)

    def get_fee_breakdown(self, duration_minutes, rule_id=None):
        if rule_id is None:
            rule = self.get_active_rule()
        else:
            rule = self.db.query_one("SELECT * FROM billing_rules WHERE id = ?", (rule_id,))

        if not rule:
            return None

        start_price = rule['start_price']
        free_minutes = rule['free_minutes']
        price_per_hour = rule['price_per_hour']
        max_price_per_day = rule['max_price_per_day']

        billable_minutes = max(0, duration_minutes - free_minutes)
        breakdown = {
            'rule_name': rule['name'],
            'duration_minutes': duration_minutes,
            'free_minutes': free_minutes,
            'billable_minutes': billable_minutes,
            'steps': []
        }

        if billable_minutes == 0:
            breakdown['steps'].append({
                'description': '免费时长内',
                'amount': 0.0
            })
            breakdown['total'] = 0.0
            breakdown['final'] = 0.0
        elif billable_minutes <= 60:
            breakdown['steps'].append({
                'description': f'计费时长≤1小时，收取起步价',
                'amount': start_price
            })
            breakdown['total'] = start_price
            breakdown['final'] = start_price
        else:
            billable_hours = billable_minutes / 60.0
            additional_hours = billable_hours - 1
            hourly_fee = additional_hours * price_per_hour
            total = start_price + hourly_fee

            breakdown['steps'].append({
                'description': '第1小时（起步价）',
                'amount': start_price
            })
            if additional_hours > 0:
                breakdown['steps'].append({
                    'description': f'超出{additional_hours:.1f}小时，按{price_per_hour}元/小时',
                    'amount': round(hourly_fee, 2)
                })
            breakdown['steps'].append({
                'description': '计算总额',
                'amount': round(total, 2)
            })

            if max_price_per_day > 0:
                days = (duration_minutes - 1) // 1440 + 1
                max_total = max_price_per_day * days
                if total > max_total:
                    breakdown['steps'].append({
                        'description': f'超过{days}天封顶价{max_total}元，触发封顶拦截',
                        'amount': round(max_total - total, 2)
                    })
                    breakdown['final'] = round(max_total, 2)
                else:
                    breakdown['final'] = round(total, 2)
            else:
                breakdown['final'] = round(total, 2)

            breakdown['total'] = round(total, 2)

        return breakdown
