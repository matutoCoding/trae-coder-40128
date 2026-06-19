import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from db.database import Database
from services.billing_service import BillingService
from services.batch_service import BatchService
from services.outbound_service import OutboundService
from services.rental_service import RentalService
from services.deployment_plan_service import DeploymentPlanService


def test_24h_cap_billing():
    print("=" * 70)
    print("【测试1】封顶价边界验证 - 按完整24小时周期算天数")
    print("=" * 70)

    db = Database(os.path.join(os.path.dirname(__file__), 'test_cap.db'))
    if os.path.exists(db.db_path):
        os.remove(db.db_path)
    db.init_database()
    billing = BillingService(db)

    test_cases = [
        (1440, 1, "24小时整 → 1天封顶"),
        (1439, 1, "23小时59分 → 1天封顶"),
        (1441, 2, "24小时1分 → 2天封顶"),
        (2880, 2, "48小时整 → 2天封顶"),
        (4319, 3, "71小时59分 → 3天封顶 (跨越3个完整24h周期)"),
        (4320, 3, "72小时整 → 3天封顶"),
        (4321, 4, "72小时1分 → 4天封顶"),
        (60, 1, "1小时 → 1天"),
        (1000, 1, "~16小时 → 1天"),
    ]

    all_passed = True
    for minutes, expected_days, desc in test_cases:
        borrow = datetime(2025, 6, 20, 10, 0, 0)
        return_time = borrow + timedelta(minutes=minutes)
        result = billing.calculate_rental_fee(borrow, return_time)

        breakdown = billing.get_fee_breakdown(minutes)

        actual_days = result['rental_days']
        status = "✅ 通过" if actual_days == expected_days else "❌ 失败"
        if actual_days != expected_days:
            all_passed = False
        print(f"\n{status} | {desc}")
        print(f"     时长: {minutes}分钟 = {minutes/60:.1f}小时")
        print(f"     期望周期天数: {expected_days}, 实际: {actual_days}")
        print(f"     实际计费: {result['calculated_amount']:.2f} → 封顶后: {result['final_amount']:.2f}元")
        if breakdown.get('total') and breakdown['total'] > breakdown['final']:
            print(f"     ✅ 封顶生效: 优惠 {breakdown['total'] - breakdown['final']:.2f}元")

    print(f"\n封顶价逻辑一致性验证: 试算明细days公式 == 实际归还金额days公式: ", end="")
    same = True
    for minutes, _, desc in test_cases:
        borrow = datetime(2025, 6, 20, 10, 0, 0)
        return_time = borrow + timedelta(minutes=minutes)
        result = billing.calculate_rental_fee(borrow, return_time)
        breakdown = billing.get_fee_breakdown(minutes)
        expected_final = breakdown.get('final', 0)
        actual_final = result['final_amount']
        if abs(expected_final - actual_final) > 0.01:
            print(f"❌ 不一致 ({desc}: 试算{expected_final} vs 实际{actual_final})")
            same = False
            all_passed = False
    if same:
        print("✅ 全部一致!")

    try:
        db.close()
        import time
        time.sleep(0.1)
        os.remove(db.db_path)
    except:
        pass
    return all_passed


def test_full_timeline_tracking():
    print("\n" + "=" * 70)
    print("【测试2】批次全链路追踪验证")
    print("=" * 70)

    db = Database(os.path.join(os.path.dirname(__file__), 'test_timeline.db'))
    if os.path.exists(db.db_path):
        os.remove(db.db_path)
    db.init_database()

    batch_service = BatchService(db)
    outbound_service = OutboundService(db)
    rental_service = RentalService(db)
    billing = BillingService(db)

    print("\n1. 创建批次 (50台设备)...")
    batch_id = batch_service.add_batch(50, "PB-20000", datetime.now().strftime('%Y-%m-%d'), "测试供应商")
    batch = batch_service.get_batch_by_id(batch_id)
    print(f"   ✅ 批次号: {batch['batch_no']}, 总数: {batch['total_quantity']}")

    outlets = batch_service.get_all_outlets()
    print(f"\n2. 分批拆分出库到3个网点...")
    outbound_service.split_outbound(batch_id, 15, outlets[0]['id'], "测试员", remark="高铁站点位铺设")
    outbound_service.split_outbound(batch_id, 15, outlets[1]['id'], "测试员", remark="购物中心点位铺设")
    outbound_service.split_outbound(batch_id, 10, outlets[2]['id'], "测试员", remark="写字楼点位铺设")
    print(f"   ✅ 已出库: {15+15+10}台, 剩余: {batch_service.get_batch_by_id(batch_id)['remaining_quantity']}台")

    print(f"\n3. 模拟设备租借/归还/故障流程...")
    devices_1 = rental_service.get_available_devices_for_rent(outlets[0]['id'])
    if devices_1:
        for i, dev in enumerate(devices_1[:3]):
            borrow_time = (datetime.now() - timedelta(hours=i * 3 + 1)).strftime('%Y-%m-%d %H:%M:%S')
            order_id = rental_service.borrow_device(dev['id'], outlets[0]['id'], borrow_time)
            return_time = (datetime.now() + timedelta(hours=i + 1)).strftime('%Y-%m-%d %H:%M:%S')
            if i < 2:
                rental_service.return_device(dev['id'], return_time)
        print(f"   ✅ {min(len(devices_1),3)}台设备完成租借流程: {sum(1 for o in rental_service.get_completed_orders() if o.get('outlet_name') == outlets[0]['name'])}单已归还")

        faulty_device = devices_1[3] if len(devices_1) > 3 else None
        if faulty_device:
            rental_service.mark_device_faulty(faulty_device['id'], "无法充电", "测试员")
            print(f"   ✅ 标记故障设备: {faulty_device['device_no']}")

    print(f"\n4. 查询批次全链路时间线...")
    timeline = batch_service.get_batch_timeline(batch_id)
    print(f"   时间线事件总数: {len(timeline)}")

    event_type_counts = {}
    for event in timeline:
        event_type_counts[event['type']] = event_type_counts.get(event['type'], 0) + 1

    required_events = ['入库', '出库']
    for req in required_events:
        if req in event_type_counts:
            print(f"   ✅ {req}: {event_type_counts[req]}次")

    if '租借' in event_type_counts:
        print(f"   ✅ 租借: {event_type_counts['租借']}次")
    if '维护' in event_type_counts:
        print(f"   ✅ 维护(故障/解锁): {event_type_counts['维护']}次")

    first_last = f"{timeline[0]['time']} ~ {timeline[-1]['time']}" if timeline else "-"
    print(f"   时间跨度: {first_last}")

    print(f"\n5. 查询单台设备全链路时间线...")
    batch = batch_service.get_batch_by_id(batch_id)
    any_device = batch['devices'][0]
    dev_timeline = batch_service.get_device_full_timeline(any_device['device_no'])
    print(f"   设备 {any_device['device_no']}: {len(dev_timeline)}条事件")
    for ev in dev_timeline:
        print(f"     [{ev['time']}] {ev['icon']} {ev['title']}")

    try:
        db.close()
        import time
        time.sleep(0.1)
        os.remove(db.db_path)
    except:
        pass
    return len(timeline) >= 4 and '入库' in event_type_counts and '出库' in event_type_counts


def test_deployment_plan():
    print("\n" + "=" * 70)
    print("【测试3】投放计划与完成率追踪")
    print("=" * 70)

    db = Database(os.path.join(os.path.dirname(__file__), 'test_plan.db'))
    if os.path.exists(db.db_path):
        os.remove(db.db_path)
    db.init_database()

    batch_service = BatchService(db)
    plan_service = DeploymentPlanService(db)
    rental_service = RentalService(db)

    print("\n1. 创建两个批次作为货源...")
    batch_id_1 = batch_service.add_batch(200, "Model-A", datetime.now().strftime('%Y-%m-%d'), "供应商A")
    batch_id_2 = batch_service.add_batch(150, "Model-B", datetime.now().strftime('%Y-%m-%d'), "供应商B")
    print(f"   ✅ 批次1: {batch_service.get_batch_by_id(batch_id_1)['batch_no']} (200台)")
    print(f"   ✅ 批次2: {batch_service.get_batch_by_id(batch_id_2)['batch_no']} (150台)")

    outlets = batch_service.get_all_outlets()
    traffic_outlets = [(o['id'], 0) for o in outlets if o.get('location_type') in ['交通枢纽', '商业综合体']]
    for i in range(len(traffic_outlets)):
        traffic_outlets[i] = (traffic_outlets[i][0], 30 if i == 0 else 25)

    print("\n2. 创建投放计划 '节前重点网点铺设' (交通枢纽+商业综合体)...")
    plan_id = plan_service.create_plan(
        plan_name="节前重点网点铺设计划",
        location_type="交通枢纽",
        target_quantity=55,
        outlet_targets=traffic_outlets,
        priority="urgent",
        plan_date=datetime.now().strftime('%Y-%m-%d'),
        operator="运营经理",
        remark="五一小长假前重点站点铺设"
    )
    plan = plan_service.get_plan_by_id(plan_id)
    print(f"   ✅ 计划号: {plan['plan_no']}, 目标: {plan['target_quantity']}台, 状态: {plan['status']}")
    print(f"   网点分配: {len(plan['outlets'])}个网点")
    for o in plan['outlets']:
        print(f"     - {o['outlet_name']}: 目标{o['target_quantity']}台, 已完成{o['completed_quantity']}台")

    print("\n3. 分多次执行计划出库...")
    first_outlet = plan['outlets'][0]
    result = plan_service.execute_plan_outlet(
        plan_id=plan_id,
        plan_outlet_id=first_outlet['id'],
        batch_id=batch_id_1,
        quantity=15,
        operator="运维小王"
    )
    print(f"   ✅ 第1次出库: 批次1→{first_outlet['outlet_name']} 15台 ({result['outbound_no']})")

    result = plan_service.execute_plan_outlet(
        plan_id=plan_id,
        plan_outlet_id=first_outlet['id'],
        batch_id=batch_id_1,
        quantity=15,
        operator="运维小李"
    )
    print(f"   ✅ 第2次出库: 批次1→{first_outlet['outlet_name']} 15台")

    second_outlet = plan['outlets'][1] if len(plan['outlets']) > 1 else first_outlet
    result = plan_service.execute_plan_outlet(
        plan_id=plan_id,
        plan_outlet_id=second_outlet['id'],
        batch_id=batch_id_2,
        quantity=second_outlet['target_quantity'] if len(plan['outlets']) > 1 else 5,
        operator="运维小张"
    )
    print(f"   ✅ 第3次出库: 批次2→{second_outlet['outlet_name']} {second_outlet['target_quantity'] if len(plan['outlets']) > 1 else 5}台")

    plan = plan_service.get_plan_by_id(plan_id)
    progress = 0 if plan['target_quantity'] == 0 else plan['completed_quantity'] / plan['target_quantity'] * 100
    print(f"\n4. 计划完成情况统计...")
    print(f"   总进度: {plan['completed_quantity']}/{plan['target_quantity']} = {progress:.1f}%")
    print(f"   当前状态: {plan['status']}")
    for o in plan['outlets']:
        p = 0 if o['target_quantity'] == 0 else o['completed_quantity'] / o['target_quantity'] * 100
        rem = o['target_quantity'] - o['completed_quantity']
        print(f"     {o['outlet_name']}: {o['completed_quantity']}/{o['target_quantity']} ({p:.1f}%) 剩余:{rem}台")

    print(f"\n5. 查询计划出库历史 ({len(plan.get('executions', []))}次执行)...")
    for exec in plan.get('executions', []):
        print(f"     {exec['outbound_date'][:16]} {exec['batch_no']}→{exec['outlet_name']} {exec['quantity']}台")

    pending = plan_service.get_pending_quantity_by_location('交通枢纽')
    print(f"\n6. 查询该类型待铺设总量: {sum(p['remaining'] for p in pending)}台")

    try:
        db.close()
        import time
        time.sleep(0.1)
        os.remove(db.db_path)
    except:
        pass
    return progress > 0 and plan['status'] in ['in_progress', 'completed']


def test_revenue_report():
    print("\n" + "=" * 70)
    print("【测试4】营收报表 - 按网点/类型汇总 + 订单明细")
    print("=" * 70)

    db = Database(os.path.join(os.path.dirname(__file__), 'test_report.db'))
    if os.path.exists(db.db_path):
        os.remove(db.db_path)
    db.init_database()

    batch_service = BatchService(db)
    outbound_service = OutboundService(db)
    rental_service = RentalService(db)

    print("\n1. 初始化数据 - 创建批次、出库、产生租借订单...")
    batch_id = batch_service.add_batch(100, "PB-MAX", datetime.now().strftime('%Y-%m-%d'), "测试厂商")
    outlets = batch_service.get_all_outlets()
    for outlet in outlets:
        qty = 15 if outlet.get('location_type') in ['交通枢纽', '商业综合体'] else 10
        outbound_service.split_outbound(batch_id, qty, outlet['id'], "测试员")

    start_date = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    print(f"   报表区间: {start_date} 至 {end_date}")

    order_count = 0
    for outlet_idx, outlet in enumerate(outlets):
        devices = rental_service.get_available_devices_for_rent(outlet['id'])
        for i in range(min(5, len(devices))):
            days_offset = outlet_idx + i
            hours_offset = (i * 2 + 1) % 72
            borrow = datetime.now() - timedelta(days=days_offset, hours=hours_offset)
            borrow_str = borrow.strftime('%Y-%m-%d %H:%M:%S')

            return_hours = (i + 1) * 8 + (outlet_idx * 5) % 24
            return_str = (borrow + timedelta(hours=return_hours)).strftime('%Y-%m-%d %H:%M:%S')

            device = devices[i]
            order_id = rental_service.borrow_device(device['id'], outlet['id'], borrow_str)
            rental_service.return_device(device['id'], return_str)
            order_count += 1

    print(f"   ✅ 生成订单: {order_count}笔")

    print(f"\n2. 按网点汇总报表...")
    report = rental_service.get_revenue_report_by_outlet(start_date, end_date)
    total_rev_all = sum(r['total_revenue'] for r in report)
    total_orders = sum(r['order_count'] for r in report)

    summary = rental_service.get_revenue_report_summary(start_date, end_date)
    print(f"   汇总: 涉及{summary.get('outlet_count',0)}个网点, {summary.get('total_orders',0)}笔订单, 营收 {summary.get('total_revenue',0):.2f}元")
    print(f"   平均客单价: {summary.get('avg_amount',0):.2f}元, 平均时长: {summary.get('avg_duration',0):.0f}分钟")

    for row_data in sorted(report, key=lambda x: -x['total_revenue'])[:5]:
        pct = 0 if total_rev_all == 0 else row_data['total_revenue'] / total_rev_all * 100
        print(f"   🏪 {row_data['outlet_name']} [{row_data.get('location_type','-')}]")
        print(f"      订单: {row_data['completed_count']}笔, 营收: {row_data['total_revenue']:.2f}元 (占{pct:.1f}%)")
        print(f"      平均: {row_data['avg_amount']:.2f}元/单, {row_data['avg_duration']:.0f}分钟/单")

    print(f"\n3. 按网点类型汇总报表...")
    type_report = rental_service.get_revenue_by_location_type(start_date, end_date)
    for t in type_report:
        if t['total_revenue'] > 0:
            print(f"   📍 {t.get('location_type','其他')}: {t['outlet_count']}个网点, "
                  f"{t['order_count']}单, 营收{t['total_revenue']:.2f}元")

    print(f"\n4. 验证 '网点订单明细' 功能...")
    top_outlet = max(report, key=lambda x: x['total_revenue'])
    detail_orders = rental_service.get_outlet_orders_detail(top_outlet['outlet_id'], start_date, end_date)
    print(f"   网点 '{top_outlet['outlet_name']}' 明细订单数: {len(detail_orders)}")

    detail_rev = sum(o['final_amount'] for o in detail_orders)
    cap_24h_count = sum(1 for o in detail_orders
                        if o.get('duration_minutes')
                        and (o['duration_minutes'] - 1) // 1440 + 1 >= 2
                        and o.get('calculated_amount', 0) > o['final_amount'])

    print(f"   明细总营收: {detail_rev:.2f}元, 报表值: {top_outlet['total_revenue']:.2f}元")
    print(f"   ✅ 营收对得上: {abs(detail_rev - top_outlet['total_revenue']) < 0.01}")
    print(f"   跨24h触发封顶订单数: {cap_24h_count}单")

    print(f"\n5. 按日营收趋势 (展示最近5天)...")
    trend = rental_service.get_daily_revenue_trend(start_date, end_date)
    for d in trend[-5:]:
        print(f"   📅 {d['stat_date']}: {d['order_count']}单, 营收{d['revenue']:.2f}元")

    try:
        db.close()
        import time
        time.sleep(0.1)
        os.remove(db.db_path)
    except:
        pass
    return summary.get('total_revenue', 0) > 0 and abs(detail_rev - top_outlet['total_revenue']) < 0.01


def main():
    print("\n" + "=" * 70)
    print("共享充电宝系统 - 四大新功能综合测试")
    print("=" * 70)

    results = {}

    try:
        results['封顶价24h周期'] = test_24h_cap_billing()
    except Exception as e:
        results['封顶价24h周期'] = False
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()

    try:
        results['全链路追踪'] = test_full_timeline_tracking()
    except Exception as e:
        results['全链路追踪'] = False
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()

    try:
        results['投放计划'] = test_deployment_plan()
    except Exception as e:
        results['投放计划'] = False
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()

    try:
        results['营收报表'] = test_revenue_report()
    except Exception as e:
        results['营收报表'] = False
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    all_pass = True
    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{status} | {name}")
        if not passed:
            all_pass = False

    print("\n" + "=" * 70)
    if all_pass:
        print("🎉 所有新功能测试全部通过!")
    else:
        print("⚠️ 部分功能未通过测试，请查看上方详情。")
    print("=" * 70)

    return all_pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
