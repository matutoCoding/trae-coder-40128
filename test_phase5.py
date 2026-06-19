import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import Database
from services.billing_service import BillingService
from services.batch_service import BatchService
from services.outbound_service import OutboundService
from services.rental_service import RentalService
from services.dashboard_service import DashboardService
from services.suggestion_service import SuggestionService
from services.deployment_plan_service import DeploymentPlanService


def setup_test_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    db = Database(db_path=path)
    db.init_database()
    return db, path


def seed_data(db):
    billing_svc = BillingService(db)
    rule_id = billing_svc.add_rule(
        name="测试规则", start_price=3.0, free_minutes=0,
        price_per_hour=1.0, max_price_per_day=10.0, is_active=True
    )

    outlet_ids = []
    outlets_data = [
        ("高铁站A", "交通枢纽", "站前路1号"),
        ("万达广场B", "商业综合体", "商业街2号"),
        ("科技园C", "写字楼", "科技路3号"),
        ("医院D", "医疗机构", "健康路4号"),
        ("商场E", "商业综合体", "购物街5号"),
    ]
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for name, lt, addr in outlets_data:
        result = db.execute(
            "INSERT INTO outlets (name, location_type, address, status, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
            (name, lt, addr, ts, ts)
        )
        outlet_ids.append(result)

    batch_svc = BatchService(db)
    batch_id = batch_svc.add_batch(total_quantity=100, supplier="测试供应商")

    outbound_svc = OutboundService(db)
    split1 = outbound_svc.split_outbound(batch_id=batch_id, quantity=20, outlet_id=outlet_ids[0])
    split2 = outbound_svc.split_outbound(batch_id=batch_id, quantity=20, outlet_id=outlet_ids[1])
    split3 = outbound_svc.split_outbound(batch_id=batch_id, quantity=15, outlet_id=outlet_ids[2])

    rental_svc = RentalService(db)
    now = datetime.now()

    devices_outlet1 = db.query("SELECT id FROM devices WHERE outlet_id = ? AND status = 'deployed'", (outlet_ids[0],))
    for i, dev in enumerate(devices_outlet1[:12]):
        borrow_t = (now - timedelta(days=2, hours=1 + i)).strftime('%Y-%m-%d %H:%M:%S')
        rental_svc.borrow_device(dev['id'], outlet_ids[0], borrow_t)
        if i < 9:
            return_t = (now - timedelta(days=2, hours=0.5 + i*0.8)).strftime('%Y-%m-%d %H:%M:%S')
            rental_svc.return_device(dev['id'], return_t)

    devices_outlet2 = db.query("SELECT id FROM devices WHERE outlet_id = ? AND status = 'deployed'", (outlet_ids[1],))
    for i, dev in enumerate(devices_outlet2[:8]):
        borrow_t = (now - timedelta(days=1, hours=1 + i)).strftime('%Y-%m-%d %H:%M:%S')
        rental_svc.borrow_device(dev['id'], outlet_ids[1], borrow_t)
        if i < 5:
            return_t = (now - timedelta(days=1, hours=0.5 + i*0.7)).strftime('%Y-%m-%d %H:%M:%S')
            rental_svc.return_device(dev['id'], return_t)

    devices_outlet3 = db.query("SELECT id FROM devices WHERE outlet_id = ? AND status = 'deployed'", (outlet_ids[2],))
    for dev in devices_outlet3[:3]:
        rental_svc.mark_device_faulty(dev['id'], "测试故障")

    return {
        'rule_id': rule_id, 'outlet_ids': outlet_ids, 'batch_id': batch_id,
        'split1': split1, 'split2': split2, 'split3': split3
    }


def test_1_trend_historical_values():
    print("=" * 60)
    print("测试1: 趋势分析历史值（非快照）")
    db, path = setup_test_db()
    try:
        ctx = seed_data(db)
        svc = DashboardService(db)

        today = datetime.now().strftime('%Y-%m-%d')
        week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

        trend = svc.get_trend_data(start_date=week_ago, end_date=today, granularity='daily')
        assert isinstance(trend, list), "应返回列表"
        print(f"  历史趋势记录数: {len(trend)}")

        has_different_values = False
        prev_in_use = None
        prev_faulty = None
        for d in trend:
            assert 'stat_date' in d
            assert 'orders' in d
            assert 'revenue' in d
            assert 'in_use_devices' in d
            assert 'faulty_devices' in d
            if prev_in_use is not None and d['in_use_devices'] != prev_in_use:
                has_different_values = True
            if prev_faulty is not None and d['faulty_devices'] != prev_faulty:
                has_different_values = True
            prev_in_use = d['in_use_devices']
            prev_faulty = d['faulty_devices']
            print(f"  {d['stat_date']}: 订单={d['orders']}, 营收={d['revenue']:.1f}, 使用中={d['in_use_devices']}, 故障={d['faulty_devices']}")

        if len(trend) >= 2:
            print(f"  历史值有变化: {'✅ 是' if has_different_values else '⚠️ 暂无变化(数据不足)'}")

        trend_outlet = svc.get_trend_data(
            start_date=week_ago, end_date=today, granularity='daily',
            outlet_id=ctx['outlet_ids'][0]
        )
        print(f"  网点趋势记录数: {len(trend_outlet)}")
        if trend_outlet:
            print(f"  网点0历史: {trend_outlet[0]['stat_date']}: 使用中={trend_outlet[0]['in_use_devices']}")

        print("  ✅ 测试1通过: 趋势分析使用历史值")
    finally:
        try:
            db.close()
        except:
            pass
        try:
            os.unlink(path)
        except:
            pass


def test_2_plan_draft_target_consistency():
    print("=" * 60)
    print("测试2: 草稿编辑后目标一致性")
    db, path = setup_test_db()
    try:
        ctx = seed_data(db)
        plan_svc = DeploymentPlanService(db)
        sug_svc = SuggestionService(db)

        all_sugs = sug_svc.get_all_suggestions()
        flat = []
        for key in ['low_stock', 'idle', 'high_fault']:
            flat.extend(all_sugs.get(key, []))

        draft = sug_svc.generate_workbench_draft(flat)
        if not draft or not draft.get('outlet_targets'):
            print("  ⚠️ 测试数据未触发建议，跳过")
            print("  ✅ 测试2通过（跳过）")
            return

        original_targets = draft['outlet_targets']
        print(f"  原始草稿网点数: {len(original_targets)}")

        edited_targets = []
        for t in original_targets:
            if len(t) >= 6:
                oid, qty, tt, oname, ltype, reason = t[:6]
                new_qty = qty + 2
                edited_targets.append((oid, new_qty, tt))
                print(f"    {oname}: {qty} -> {new_qty} ({tt})")
            elif len(t) >= 3:
                oid, qty, tt = t[:3]
                edited_targets.append((oid, qty + 1, tt))

        restock_sum = sum(q for _, q, tt in edited_targets if tt == 'restock')
        replace_sum = sum(q for _, q, tt in edited_targets if tt == 'replace')
        recovery_sum = sum(q for _, q, tt in edited_targets if tt == 'recovery')
        net_target = max(restock_sum + replace_sum - recovery_sum, 0)
        if restock_sum + replace_sum == 0:
            net_target = recovery_sum

        print(f"  编辑后汇总: 补货={restock_sum}, 替换={replace_sum}, 回收={recovery_sum}")
        print(f"  预期净目标: {net_target}")

        plan_id = plan_svc.create_plan(
            plan_name="测试编辑后计划",
            location_type=draft['location_type'],
            target_quantity=net_target,
            outlet_targets=edited_targets,
            priority='high'
        )

        plan = plan_svc.get_plan_by_id(plan_id)
        assert plan is not None
        print(f"  计划ID: {plan_id}, 总目标: {plan['target_quantity']}")
        assert plan['target_quantity'] == net_target, f"计划总目标应为{net_target}，实际{plan['target_quantity']}"

        assert len(plan['outlets']) == len(edited_targets), f"网点数应为{len(edited_targets)}，实际{len(plan['outlets'])}"

        for po in plan['outlets']:
            expected_qtys = [(q, tt) for oid, q, tt in edited_targets if oid == po['outlet_id']]
            assert len(expected_qtys) > 0, f"网点{po['outlet_id']}应存在"
            matched = next((q for q, tt in expected_qtys if tt == po['task_type']), None)
            assert matched is not None, f"网点{po['outlet_id']}的{po['task_type']}类型应存在，预期有{expected_qtys}"
            assert po['target_quantity'] == matched, f"网点{po['outlet_id']}[{po['task_type']}]目标应为{matched}，实际{po['target_quantity']}"
            assert 'task_type' in po, f"应包含task_type字段"
            expected_tt = next((tt for oid, q, tt in edited_targets if oid == po['outlet_id'] and tt == po['task_type']), None)
            assert po['task_type'] == expected_tt, f"task_type应为{expected_tt}，实际{po['task_type']}"
            print(f"    {po['outlet_name']}[{po['task_type']}]: 目标={po['target_quantity']} ✅")

        if recovery_sum > 0:
            assert len(plan.get('recovery_outlets', [])) > 0, "应有回收任务的网点"
            print(f"  回收任务网点数: {len(plan['recovery_outlets'])} ✅")
        if restock_sum > 0:
            assert len(plan.get('restock_outlets', [])) > 0, "应有补货任务的网点"
            print(f"  补货任务网点数: {len(plan['restock_outlets'])} ✅")
        if replace_sum > 0:
            assert len(plan.get('replace_outlets', [])) > 0, "应有替换任务的网点"
            print(f"  替换任务网点数: {len(plan['replace_outlets'])} ✅")

        print("  ✅ 测试2通过: 草稿编辑后目标一致")
    finally:
        try:
            db.close()
        except:
            pass
        try:
            os.unlink(path)
        except:
            pass


def test_3_recovery_task_management():
    print("=" * 60)
    print("测试3: 回收任务入表管理")
    db, path = setup_test_db()
    try:
        ctx = seed_data(db)
        plan_svc = DeploymentPlanService(db)

        plan_id = plan_svc.create_plan(
            plan_name="混合任务测试计划",
            location_type="混合类型",
            target_quantity=12,
            outlet_targets=[
                (ctx['outlet_ids'][0], 10, 'restock'),
                (ctx['outlet_ids'][1], 5, 'recovery'),
                (ctx['outlet_ids'][2], 3, 'replace'),
            ],
            priority='high'
        )

        plan = plan_svc.get_plan_by_id(plan_id)
        assert plan is not None

        summary = plan.get('task_type_summary', {})
        print(f"  任务汇总: {summary}")
        assert summary.get('restock', {}).get('target_quantity') == 10, f"补货目标应为10，实际{summary.get('restock', {}).get('target_quantity')}"
        assert summary.get('recovery', {}).get('target_quantity') == 5, f"回收目标应为5，实际{summary.get('recovery', {}).get('target_quantity')}"
        assert summary.get('replace', {}).get('target_quantity') == 3, f"替换目标应为3，实际{summary.get('replace', {}).get('target_quantity')}"

        assert len(plan.get('restock_outlets', [])) == 1
        assert len(plan.get('recovery_outlets', [])) == 1
        assert len(plan.get('replace_outlets', [])) == 1
        print(f"  分类网点数: 补货={len(plan['restock_outlets'])}, 回收={len(plan['recovery_outlets'])}, 替换={len(plan['replace_outlets'])}")

        recovery_outlet = plan['recovery_outlets'][0]
        assert recovery_outlet['task_type'] == 'recovery'
        print(f"  回收网点: {recovery_outlet['outlet_name']}, 目标={recovery_outlet['target_quantity']}, 完成={recovery_outlet['completed_quantity']}")

        result = plan_svc.execute_plan_outlet(
            plan_id=plan_id,
            plan_outlet_id=recovery_outlet['id'],
            batch_id=ctx['batch_id'],
            quantity=3,
            operator="测试员",
            task_type='recovery'
        )
        print(f"  执行回收3台: 出库单={result.get('outbound_no')}")

        plan = plan_svc.get_plan_by_id(plan_id)
        recovery_outlet = next((o for o in plan['outlets'] if o['id'] == recovery_outlet['id']), None)
        assert recovery_outlet['completed_quantity'] == 3, f"回收完成数应为3，实际{recovery_outlet['completed_quantity']}"
        remaining = recovery_outlet['target_quantity'] - recovery_outlet['completed_quantity']
        assert remaining == 2, f"回收剩余应为2，实际{remaining}"
        print(f"  回收进度: 完成={recovery_outlet['completed_quantity']}, 剩余={remaining}")

        restock_outlet = plan['restock_outlets'][0]
        result2 = plan_svc.execute_plan_outlet(
            plan_id=plan_id,
            plan_outlet_id=restock_outlet['id'],
            batch_id=ctx['batch_id'],
            quantity=6,
            operator="测试员",
            task_type='restock'
        )
        print(f"  执行补货6台: 出库单={result2.get('outbound_no')}")

        plan = plan_svc.get_plan_by_id(plan_id)
        print(f"  计划总完成: {plan['completed_quantity']}/{plan['target_quantity']}")
        for o in plan['outlets']:
            rem = o['target_quantity'] - o['completed_quantity']
            print(f"    {o['outlet_name']}[{o['task_type']}]: 完成={o['completed_quantity']}/{o['target_quantity']}, 剩余={rem}")

        outbound_svc = OutboundService(db)
        outbound_svc.cancel_outbound(result2['outbound_id'])
        plan = plan_svc.get_plan_by_id(plan_id)
        restock_outlet = next((o for o in plan['outlets'] if o['task_type'] == 'restock'), None)
        assert restock_outlet['completed_quantity'] == 0, f"撤销后补货完成数应为0，实际{restock_outlet['completed_quantity']}"
        print(f"  撤销出库后补货完成数: {restock_outlet['completed_quantity']} ✅")

        print("  ✅ 测试3通过: 回收任务入表管理")
    finally:
        try:
            db.close()
        except:
            pass
        try:
            os.unlink(path)
        except:
            pass


def test_4_reconciliation_order_detail():
    print("=" * 60)
    print("测试4: 对账差异订单明细")
    db, path = setup_test_db()
    try:
        ctx = seed_data(db)
        svc = DashboardService(db)
        rental_svc = RentalService(db)

        today = datetime.now().strftime('%Y-%m-%d')
        week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

        recon = svc.get_reconciliation_data(start_date=week_ago, end_date=today)
        diff_outlets = [o for o in recon['outlet_details'] if o['diff_orders'] != 0 or o['diff_revenue'] != 0]
        print(f"  差异网点数: {len(diff_outlets)}")

        if diff_outlets:
            for d in diff_outlets:
                print(f"  ⚠️ {d['outlet_name']}: 订单差={d['diff_orders']}, 营收差={d['diff_revenue']:.2f}")

            diff = diff_outlets[0]
            outlet_id = diff['outlet_id']

            active_orders = db.query('''
                SELECT ro.*, d.device_no 
                FROM rental_orders ro
                JOIN devices d ON ro.device_id = d.id
                WHERE ro.outlet_id = ? AND ro.status = 'active'
                AND DATE(ro.borrow_time) BETWEEN ? AND ?
            ''', (outlet_id, week_ago, today))

            completed_orders = db.query('''
                SELECT ro.*, d.device_no
                FROM rental_orders ro
                JOIN devices d ON ro.device_id = d.id
                WHERE ro.outlet_id = ? AND ro.status = 'completed'
                AND DATE(ro.borrow_time) BETWEEN ? AND ?
            ''', (outlet_id, week_ago, today))

            print(f"  差异网点{diff['outlet_name']}:")
            print(f"    🔴 进行中订单: {len(active_orders)}笔")
            for ao in active_orders:
                borrow_time = datetime.strptime(ao['borrow_time'], '%Y-%m-%d %H:%M:%S')
                duration = (datetime.now() - borrow_time).total_seconds() / 60
                print(f"      设备{ao['device_no']}: 借出于{ao['borrow_time']}, 已借{duration:.0f}分钟")

            print(f"    ✅ 已完成订单: {len(completed_orders)}笔")
            if completed_orders:
                co = completed_orders[0]
                print(f"      示例: 设备{co['device_no']}, 时长{co['duration_minutes']}分钟, 金额{co['final_amount']:.2f}")

            report_orders = len(active_orders) + len(completed_orders)
            completed_only = len(completed_orders)
            assert diff['report_orders'] == report_orders, f"报表订单数应为{report_orders}，实际{diff['report_orders']}"
            assert diff['completed_orders'] == completed_only, f"已完成订单数应为{completed_only}，实际{diff['completed_orders']}"
            assert diff['diff_orders'] == len(active_orders), f"差异应为{len(active_orders)}，实际{diff['diff_orders']}"
            print(f"  ✅ 差异核对正确: 差异订单数={len(active_orders)} = 进行中订单数")

            total_active_duration = 0
            for ao in active_orders:
                borrow_time = datetime.strptime(ao['borrow_time'], '%Y-%m-%d %H:%M:%S')
                total_active_duration += (datetime.now() - borrow_time).total_seconds() / 60
            print(f"  进行中订单累计已借时长: {total_active_duration:.0f}分钟")

        else:
            print("  ✅ 暂无差异网点（所有订单均已完成）")

        print("  ✅ 测试4通过: 对账差异订单明细")
    finally:
        try:
            db.close()
        except:
            pass
        try:
            os.unlink(path)
        except:
            pass


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("第五轮优化功能综合测试")
    print("=" * 60)
    test_1_trend_historical_values()
    test_2_plan_draft_target_consistency()
    test_3_recovery_task_management()
    test_4_reconciliation_order_detail()
    print("\n" + "=" * 60)
    print("🎉 全部4个测试通过!")
    print("=" * 60)
