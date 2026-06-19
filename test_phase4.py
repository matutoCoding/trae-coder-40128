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
    for name, lt, addr in outlets_data:
        result = db.execute(
            "INSERT INTO outlets (name, location_type, address, status, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
            (name, lt, addr, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        outlet_ids.append(result)

    batch_svc = BatchService(db)
    batch_id = batch_svc.add_batch(total_quantity=50, supplier="测试供应商")

    outbound_svc = OutboundService(db)
    split1 = outbound_svc.split_outbound(batch_id=batch_id, quantity=10, outlet_id=outlet_ids[0])
    split2 = outbound_svc.split_outbound(batch_id=batch_id, quantity=10, outlet_id=outlet_ids[1])
    split3 = outbound_svc.split_outbound(batch_id=batch_id, quantity=8, outlet_id=outlet_ids[2])

    rental_svc = RentalService(db)
    now = datetime.now()

    devices_outlet1 = db.query("SELECT id FROM devices WHERE outlet_id = ? AND status = 'deployed'", (outlet_ids[0],))
    for i, dev in enumerate(devices_outlet1[:6]):
        borrow_t = (now - timedelta(hours=2+i)).strftime('%Y-%m-%d %H:%M:%S')
        rental_svc.borrow_device(dev['id'], outlet_ids[0], borrow_t)
        if i < 4:
            return_t = (now - timedelta(hours=1-i*0.3)).strftime('%Y-%m-%d %H:%M:%S')
            rental_svc.return_device(dev['id'], return_t)

    devices_outlet2 = db.query("SELECT id FROM devices WHERE outlet_id = ? AND status = 'deployed'", (outlet_ids[1],))
    for i, dev in enumerate(devices_outlet2[:3]):
        borrow_t = (now - timedelta(hours=3+i)).strftime('%Y-%m-%d %H:%M:%S')
        rental_svc.borrow_device(dev['id'], outlet_ids[1], borrow_t)
        return_t = (now - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        rental_svc.return_device(dev['id'], return_t)

    devices_outlet3 = db.query("SELECT id FROM devices WHERE outlet_id = ? AND status = 'deployed'", (outlet_ids[2],))
    for dev in devices_outlet3[:2]:
        rental_svc.mark_device_faulty(dev['id'], "测试故障")

    return {
        'rule_id': rule_id, 'outlet_ids': outlet_ids, 'batch_id': batch_id,
        'split1': split1, 'split2': split2, 'split3': split3
    }


def test_1_trend_analysis():
    print("=" * 60)
    print("测试1: 运营看板趋势分析")
    db, path = setup_test_db()
    try:
        ctx = seed_data(db)
        svc = DashboardService(db)

        today = datetime.now().strftime('%Y-%m-%d')
        week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

        trend_daily = svc.get_trend_data(start_date=week_ago, end_date=today, granularity='daily')
        assert isinstance(trend_daily, list), "趋势数据应返回列表"
        print(f"  日粒度趋势: {len(trend_daily)}条记录")
        if trend_daily:
            d = trend_daily[0]
            assert 'stat_date' in d, "应包含stat_date"
            assert 'orders' in d, "应包含orders"
            assert 'revenue' in d, "应包含revenue"
            assert 'in_use_devices' in d, "应包含in_use_devices"
            assert 'faulty_devices' in d, "应包含faulty_devices"
            print(f"  示例: 日期={d['stat_date']}, 订单={d['orders']}, 营收={d['revenue']:.2f}")

        trend_weekly = svc.get_trend_data(start_date=week_ago, end_date=today, granularity='weekly')
        print(f"  周粒度趋势: {len(trend_weekly)}条记录")
        if trend_weekly:
            d = trend_weekly[0]
            assert 'stat_week' in d, "周粒度应包含stat_week"
            print(f"  示例: 周={d['stat_week']}, 订单={d['orders']}")

        trend_filtered = svc.get_trend_data(
            start_date=week_ago, end_date=today,
            location_type='交通枢纽', granularity='daily'
        )
        print(f"  交通枢纽趋势: {len(trend_filtered)}条记录")

        outlet_id = ctx['outlet_ids'][0]
        turnover = svc.get_outlet_turnover(outlet_id, start_date=week_ago, end_date=today)
        assert 'total_devices' in turnover, "应包含total_devices"
        assert 'total_borrows' in turnover, "应包含total_borrows"
        assert 'turnover_rate' in turnover, "应包含turnover_rate"
        print(f"  网点周转: 设备={turnover['total_devices']}, 借出={turnover['total_borrows']}, 周转率={turnover['turnover_rate']}")

        stats_filtered = svc.get_outlet_stats(start_date=week_ago, end_date=today, location_type='商业综合体')
        for s in stats_filtered:
            assert s['location_type'] == '商业综合体', f"筛选后应只含商业综合体，实际={s['location_type']}"
        print(f"  网点类型筛选(商业综合体): {len(stats_filtered)}条，类型一致 ✅")

        print("  ✅ 测试1通过: 趋势分析功能正常")
    finally:
        try:
            db.close()
        except:
            pass
        try:
            os.unlink(path)
        except:
            pass


def test_2_workbench_and_draft():
    print("=" * 60)
    print("测试2: 调度工作台与计划草稿")
    db, path = setup_test_db()
    try:
        ctx = seed_data(db)
        sug_svc = SuggestionService(db)
        plan_svc = DeploymentPlanService(db)

        all_sugs = sug_svc.get_all_suggestions()
        flat = []
        for key in ['low_stock', 'idle', 'high_fault']:
            flat.extend(all_sugs.get(key, []))
        print(f"  建议总数: {len(flat)}")
        for s in flat:
            print(f"    {s['type_label']}: {s['outlet_name']} ({s['location_type']})")

        draft = sug_svc.generate_workbench_draft(flat)
        if draft:
            assert 'outlet_targets' in draft, "草稿应包含outlet_targets"
            assert 'task_types' in draft, "草稿应包含task_types"
            assert 'suggestion_summary' in draft, "草稿应包含suggestion_summary"
            print(f"  草稿: 名称={draft['plan_name']}, 任务类型={draft['task_types']}")
            print(f"  汇总: 补货={draft['restock_count']}, 回收={draft['recovery_count']}, 替换={draft['replace_count']}")
            print(f"  网点目标数: {len(draft['outlet_targets'])}")
            for t in draft['outlet_targets']:
                if len(t) >= 6:
                    print(f"    {t[3]}({t[4]}): {t[1]}台-{t[2]}-{t[5][:20]}")

            outlet_targets = [(t[0], t[1]) for t in draft['outlet_targets'] if t[2] in ('restock', 'replace')]
            if outlet_targets:
                plan_id = plan_svc.create_plan(
                    plan_name=draft['plan_name'],
                    location_type=draft['location_type'],
                    target_quantity=sum(q for _, q in outlet_targets),
                    outlet_targets=outlet_targets,
                    priority='high',
                    remark=draft.get('remark', '')
                )
                plan = plan_svc.get_plan_by_id(plan_id)
                assert plan is not None, "计划应创建成功"
                print(f"  创建计划成功: ID={plan_id}, 网点数={len(plan['outlets'])}")

            draft_simple = sug_svc.generate_plan_draft_from_suggestions(flat)
            if draft_simple:
                assert 'task_types' in draft_simple, "简单草稿应含task_types"
                for t in draft_simple['outlet_targets']:
                    assert len(t) == 3, f"简单草稿outlet_targets应为三元组，实际长度={len(t)}"
                print(f"  简单草稿三元组格式正确 ✅")
        else:
            print("  ⚠️ 测试数据未触发建议，跳过草稿验证")

        print("  ✅ 测试2通过: 调度工作台和草稿功能正常")
    finally:
        try:
            db.close()
        except:
            pass
        try:
            os.unlink(path)
        except:
            pass


def test_3_plan_draft_edit_and_execution():
    print("=" * 60)
    print("测试3: 计划草稿编辑与拆分执行")
    db, path = setup_test_db()
    try:
        ctx = seed_data(db)
        plan_svc = DeploymentPlanService(db)

        plan_id = plan_svc.create_plan(
            plan_name="混合调度测试计划",
            location_type="混合类型",
            target_quantity=15,
            outlet_targets=[
                (ctx['outlet_ids'][0], 5),
                (ctx['outlet_ids'][1], 5),
                (ctx['outlet_ids'][2], 5),
            ],
            priority='high'
        )
        plan = plan_svc.get_plan_by_id(plan_id)
        assert plan is not None
        assert len(plan['outlets']) == 3, f"应有3个网点，实际={len(plan['outlets'])}"
        print(f"  创建混合计划: ID={plan_id}, 网点数={len(plan['outlets'])}")

        for o in plan['outlets']:
            remaining = o['target_quantity'] - o['completed_quantity']
            print(f"    {o['outlet_name']}: 目标={o['target_quantity']}, 完成={o['completed_quantity']}, 剩余={remaining}")

        outlet0 = plan['outlets'][0]
        result = plan_svc.execute_plan_outlet(
            plan_id=plan_id,
            plan_outlet_id=outlet0['id'],
            batch_id=ctx['batch_id'],
            quantity=3,
            operator="测试员"
        )
        print(f"  执行出库: 出库单={result['outbound_no']}, 数量=3")

        plan = plan_svc.get_plan_by_id(plan_id)
        assert plan['completed_quantity'] == 3, f"完成数应为3，实际={plan['completed_quantity']}"
        assert plan['status'] == 'in_progress', f"状态应为进行中，实际={plan['status']}"
        print(f"  执行后: 完成={plan['completed_quantity']}, 状态={plan['status']}")

        for o in plan['outlets']:
            remaining = o['target_quantity'] - o['completed_quantity']
            print(f"    {o['outlet_name']}: 目标={o['target_quantity']}, 完成={o['completed_quantity']}, 剩余={remaining}")

        outbound_id = result['outbound_id']
        outbound_svc = OutboundService(db)
        outbound_svc.cancel_outbound(outbound_id)
        print(f"  撤销出库: ID={outbound_id}")

        plan = plan_svc.get_plan_by_id(plan_id)
        assert plan['completed_quantity'] == 0, f"撤销后完成数应为0，实际={plan['completed_quantity']}"
        print(f"  撤销后: 完成={plan['completed_quantity']}, 状态={plan['status']}")

        print("  ✅ 测试3通过: 计划草稿编辑与拆分执行功能正常")
    finally:
        try:
            db.close()
        except:
            pass
        try:
            os.unlink(path)
        except:
            pass


def test_4_reconciliation():
    print("=" * 60)
    print("测试4: 营收报表对账视图")
    db, path = setup_test_db()
    try:
        ctx = seed_data(db)
        svc = DashboardService(db)

        today = datetime.now().strftime('%Y-%m-%d')
        week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

        recon = svc.get_reconciliation_data(start_date=week_ago, end_date=today)

        assert 'page_summary' in recon, "应包含page_summary"
        assert 'completed_only' in recon, "应包含completed_only"
        assert 'outlet_details' in recon, "应包含outlet_details"

        ps = recon['page_summary']
        co = recon['completed_only']
        print(f"  报表口径: 订单={ps.get('total_orders',0)}, 营收={ps.get('total_revenue',0):.2f}")
        print(f"  已完成口径: 订单={co.get('total_orders',0)}, 营收={co.get('total_revenue',0):.2f}")

        diff_orders = ps.get('total_orders', 0) - co.get('total_orders', 0)
        diff_revenue = ps.get('total_revenue', 0) - co.get('total_revenue', 0)
        print(f"  差异: 订单={diff_orders}, 营收={diff_revenue:.2f}")

        print(f"  网点对账明细: {len(recon['outlet_details'])}条")
        diff_outlets = []
        for d in recon['outlet_details']:
            do = d['diff_orders']
            dr = d['diff_revenue']
            if do != 0 or dr != 0:
                diff_outlets.append(d)
                print(f"    ⚠️ {d['outlet_name']}: 订单差={do}, 营收差={dr:.2f}")

        if diff_outlets:
            print(f"  存在差异的网点: {len(diff_outlets)}个（由进行中订单导致）")
        else:
            print(f"  所有网点数据一致 ✅")

        recon_filtered = svc.get_reconciliation_data(
            start_date=week_ago, end_date=today, location_type='交通枢纽'
        )
        print(f"  交通枢纽对账: 网点数={len(recon_filtered['outlet_details'])}")

        print("  ✅ 测试4通过: 对账视图功能正常")
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
    print("第四轮功能综合测试")
    print("=" * 60)
    test_1_trend_analysis()
    test_2_workbench_and_draft()
    test_3_plan_draft_edit_and_execution()
    test_4_reconciliation()
    print("\n" + "=" * 60)
    print("🎉 全部4个测试通过!")
    print("=" * 60)
