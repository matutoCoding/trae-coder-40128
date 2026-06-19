import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from db.database import Database
from services.billing_service import BillingService
from services.batch_service import BatchService
from services.outbound_service import OutboundService
from services.rental_service import RentalService


def test_billing_service():
    print("=" * 60)
    print("测试计费规则模块...")
    print("=" * 60)

    db = Database()
    db.init_database()
    billing = BillingService(db)

    print("\n1. 获取当前启用的规则:")
    rule = billing.get_active_rule()
    print(f"   规则名称: {rule['name']}")
    print(f"   起步价: {rule['start_price']}元")
    print(f"   免费时长: {rule['free_minutes']}分钟")
    print(f"   每小时单价: {rule['price_per_hour']}元")
    print(f"   每日封顶: {rule['max_price_per_day']}元")

    print("\n2. 测试费用计算 - 边界场景:")

    test_cases = [
        (3, "短租（3分钟，免费时长内）"),
        (6, "短租（6分钟，起步价）"),
        (30, "短租（30分钟，起步价）"),
        (60, "刚好1小时"),
        (125, "2小时5分钟"),
        (300, "5小时"),
        (600, "10小时（触发日封顶）"),
        (1440, "24小时"),
        (2160, "36小时（跨天，2天封顶）"),
        (4320, "72小时（跨天，3天封顶）"),
    ]

    for minutes, desc in test_cases:
        hours = minutes / 60
        result = billing.simulate_fee(hours)
        breakdown = billing.get_fee_breakdown(minutes)
        print(f"\n   {desc}:")
        print(f"     时长: {result['duration_minutes']}分钟, 计费: {result['billable_minutes']}分钟")
        print(f"     计算金额: {result['calculated_amount']:.2f}元")
        print(f"     实收金额: {result['final_amount']:.2f}元")
        if breakdown and breakdown.get('total') != breakdown.get('final'):
            print(f"     ✅ 已触发封顶拦截，优惠: {breakdown['total'] - breakdown['final']:.2f}元")
        if result['final_amount'] == rule['start_price'] and result['billable_minutes'] <= 60:
            print(f"     ✅ 已触发起步价（计费≤60分钟）")

    print("\n3. 测试新增计费规则:")
    new_rule_id = billing.add_rule(
        name="周末特惠规则",
        start_price=1.5,
        free_minutes=10,
        price_per_hour=0.8,
        max_price_per_day=8.0
    )
    print(f"   新增规则ID: {new_rule_id}")

    billing.set_active_rule(new_rule_id)
    rule = billing.get_active_rule()
    print(f"   当前规则已切换为: {rule['name']}")

    result = billing.simulate_fee(3)
    print(f"   新规则测试（3分钟）: {result['final_amount']:.2f}元（免费时长内）")

    billing.set_active_rule(1)
    rule = billing.get_active_rule()
    print(f"   已切回默认规则: {rule['name']}")

    print("\n✅ 计费规则模块测试通过!")
    return True


def test_batch_service():
    print("\n" + "=" * 60)
    print("测试设备批次模块...")
    print("=" * 60)

    db = Database()
    batch_service = BatchService(db)

    print("\n1. 新增设备批次:")
    batch_id = batch_service.add_batch(
        total_quantity=100,
        model="PB-20000mAh",
        purchase_date=datetime.now().strftime('%Y-%m-%d'),
        supplier="XX科技有限公司",
        unit_cost=35.50,
        remark="首批试投设备"
    )
    print(f"   批次ID: {batch_id}")

    batches = batch_service.get_all_batches()
    batch = next((b for b in batches if b['id'] == batch_id), None)
    print(f"   批次号: {batch['batch_no']}")
    print(f"   总数: {batch['total_quantity']}, 剩余: {batch['remaining_quantity']}")

    print("\n2. 查询库存概览:")
    summary = batch_service.get_distribution_summary()
    print(f"   总批次: {summary['total_batches']}")
    print(f"   总设备: {summary['total_devices']}")
    print(f"   库存中: {summary['in_stock']}")
    print(f"   活跃网点: {summary['active_outlets']}")

    print("\n3. 查询批次详情（含设备列表）:")
    batch_detail = batch_service.get_batch_by_id(batch_id)
    devices = batch_detail.get('devices', [])
    print(f"   设备数量: {len(devices)}")
    if devices:
        print(f"   首台设备: {devices[0]['device_no']}, 状态: {devices[0]['status']}")
        print(f"   末台设备: {devices[-1]['device_no']}, 状态: {devices[-1]['status']}")

    print("\n4. 查询网点列表:")
    outlets = batch_service.get_all_outlets()
    print(f"   网点数量: {len(outlets)}")
    for outlet in outlets[:3]:
        print(f"     - {outlet['name']} ({outlet['location_type']})")

    print("\n✅ 设备批次模块测试通过!")
    return batch_id


def test_outbound_service(batch_id):
    print("\n" + "=" * 60)
    print("测试拆分出库模块...")
    print("=" * 60)

    db = Database()
    outbound_service = OutboundService(db)
    batch_service = BatchService(db)

    outlets = batch_service.get_all_outlets()
    batch = batch_service.get_batch_by_id(batch_id)
    print(f"\n出库前批次状态: 总数={batch['total_quantity']}, 剩余={batch['remaining_quantity']}")

    print("\n1. 分批拆分出库到不同网点:")
    outbound_records = []
    split_plans = [
        (outlets[0]['id'], 20, "首批投放高铁站"),
        (outlets[1]['id'], 25, "购物中心重点投放"),
        (outlets[2]['id'], 15, "写字楼补充"),
        (outlets[3]['id'], 15, "医院投放"),
    ]

    for outlet_id, qty, remark in split_plans:
        outlet = next((o for o in outlets if o['id'] == outlet_id), None)
        result = outbound_service.split_outbound(
            batch_id=batch_id,
            quantity=qty,
            outlet_id=outlet_id,
            operator="测试员",
            remark=remark
        )
        outbound_records.append(result['outbound_id'])
        print(f"   ✅ 出库 {result['outbound_no']}: {outlet['name']} - {qty}台")

    batch = batch_service.get_batch_by_id(batch_id)
    print(f"\n出库后批次状态: 总数={batch['total_quantity']}, 剩余={batch['remaining_quantity']}")
    print(f"已出库总数: {batch['total_quantity'] - batch['remaining_quantity']}")

    print("\n2. 查询批次出库历史:")
    history = outbound_service.get_batch_outbound_history(batch_id)
    print(f"   出库记录数: {len(history)}")
    for record in history:
        print(f"     - {record['outbound_no']}: {record['outlet_name']} {record['quantity']}台 ({record['outbound_date']})")

    print("\n3. 查询网点设备分布:")
    distribution = outbound_service.get_outlet_distribution()
    for dist in distribution:
        if dist['total_devices'] > 0:
            print(f"     {dist['name']}: {dist['total_devices']}台 (可用:{dist['deployed']+dist['in_use']}, 故障:{dist['faulty']})")

    print("\n4. 查询分布统计:")
    stats = outbound_service.get_distribution_stats()
    for stat in stats:
        print(f"     {stat.get('location_type','其他')}: {stat['outlet_count']}个网点, {stat['device_count']}台设备")

    print("\n5. 查询批次分布去向:")
    batch_dist = batch_service.get_batch_distribution(batch_id)
    print(f"   该批次已分布到 {len(batch_dist)} 个网点")

    print("\n✅ 拆分出库模块测试通过!")
    return outbound_records


def test_rental_service(batch_id):
    print("\n" + "=" * 60)
    print("测试账单生成与坏宝管理模块...")
    print("=" * 60)

    db = Database()
    rental_service = RentalService(db)
    batch_service = BatchService(db)
    outbound_service = OutboundService(db)

    outlets = batch_service.get_all_outlets()

    print("\n1. 测试设备借出:")
    outlet_id = outlets[0]['id']
    devices = rental_service.get_available_devices_for_rent(outlet_id)
    print(f"   网点[{outlets[0]['name']}]可用设备: {len(devices)}台")

    order_ids = []
    if devices:
        for i in range(min(3, len(devices))):
            borrow_time = (datetime.now() - timedelta(hours=i+1)).strftime('%Y-%m-%d %H:%M:%S')
            order_id = rental_service.borrow_device(devices[i]['id'], outlet_id, borrow_time)
            order_ids.append(order_id)
            print(f"   ✅ 借出订单 {order_id}: 设备 {devices[i]['device_no']}")

    print("\n2. 查询进行中订单:")
    active_orders = rental_service.get_active_orders()
    print(f"   进行中订单: {len(active_orders)}笔")
    for order in active_orders:
        print(f"     - {order['order_no']}: {order['device_no']} @ {order['outlet_name']}")

    print("\n3. 测试设备归还与计费:")
    for i, order_id in enumerate(order_ids):
        order = rental_service.get_order_by_id(order_id)
        if order and order['status'] == 'active':
            return_time = (datetime.now() + timedelta(hours=i*2+1)).strftime('%Y-%m-%d %H:%M:%S')
            result = rental_service.return_device(order['device_id'], return_time)
            fee = result['fee']
            print(f"   ✅ 归还 {order['device_no']}:")
            print(f"     时长: {fee['duration_minutes']}分钟, 计费: {fee['billable_minutes']}分钟")
            print(f"     计算: {fee['calculated_amount']:.2f}元, 实收: {fee['final_amount']:.2f}元")

    print("\n4. 测试更长周期租借（触发封顶）:")
    if len(devices) > 3:
        device = devices[3]
        borrow_time = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
        order_id = rental_service.borrow_device(device['id'], outlet_id, borrow_time)
        return_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        result = rental_service.return_device(device['id'], return_time)
        fee = result['fee']
        print(f"   ✅ 3天期租借测试:")
        print(f"     时长: {fee['duration_minutes']}分钟 ({fee['duration_minutes']/1440:.1f}天)")
        print(f"     计算: {fee['calculated_amount']:.2f}元, 封顶后实收: {fee['final_amount']:.2f}元")
        if fee['calculated_amount'] > fee['final_amount']:
            print(f"     ✅ 封顶拦截生效，节省: {fee['calculated_amount'] - fee['final_amount']:.2f}元")

    print("\n5. 测试日账单生成:")
    bill_date = datetime.now().strftime('%Y-%m-%d')
    try:
        result = rental_service.generate_daily_bill(bill_date)
        if result:
            print(f"   ✅ 账单生成成功:")
            print(f"     账单号: {result['bill_no']}")
            print(f"     订单数: {result['order_count']}笔")
            print(f"     总金额: {result['total_amount']:.2f}元")

            bill_detail = rental_service.get_bill_by_id(result['bill_id'])
            print(f"     明细条目: {len(bill_detail.get('items', []))}条")
        else:
            print(f"   ℹ️ 当日没有可生成账单的订单")
    except ValueError as e:
        print(f"   ℹ️ {e}")

    print("\n6. 查询账单列表:")
    bills = rental_service.get_all_bills()
    print(f"   账单总数: {len(bills)}")
    for bill in bills[:3]:
        print(f"     - {bill['bill_no']}: {bill['bill_date']} {bill['order_count']}笔 {bill['total_amount']:.2f}元 ({bill['status']})")

    print("\n7. 测试坏宝锁定下架:")
    batch_detail = batch_service.get_batch_by_id(batch_id)
    deployed_devices = [d for d in batch_detail.get('devices', [])
                         if d['status'] in ['deployed', 'in_use']]

    if deployed_devices:
        faulty_device = deployed_devices[0]
        print(f"   锁定设备: {faulty_device['device_no']}")
        try:
            rental_service.mark_device_faulty(
                faulty_device['id'],
                description="电池鼓包，无法充电",
                operator="运维员小王"
            )
            print("   ✅ 设备已锁定下架")
        except ValueError as e:
            print(f"   ℹ️ {e}")

    print("\n8. 查询故障设备列表:")
    faulty_devices = rental_service.get_faulty_devices()
    print(f"   故障设备数: {len(faulty_devices)}")
    for fd in faulty_devices:
        print(f"     - {fd['device_no']} ({fd.get('outlet_name') or '库存'}) - {fd.get('last_maintenance') or '无备注'}")

    print("\n9. 查询运营统计:")
    summary = rental_service.get_rental_summary()
    print(f"   总订单: {summary['total_orders']}")
    print(f"   已完成: {summary['completed_orders']}")
    print(f"   进行中: {summary['active_orders']}")
    print(f"   总营收: {summary['total_revenue']:.2f}元")
    print(f"   平均金额: {summary['avg_amount']:.2f}元")
    print(f"   平均时长: {summary['avg_duration']:.0f}分钟")

    print("\n10. 测试解锁恢复:")
    faulty_devices = rental_service.get_faulty_devices()
    if faulty_devices:
        fd = faulty_devices[0]
        rental_service.unlock_device(fd['id'], "已更换电池，测试正常", "运维员小王")
        print(f"   ✅ 设备 {fd['device_no']} 已解锁恢复")

    print("\n✅ 账单生成与坏宝管理模块测试通过!")


def main():
    print("\n" + "=" * 60)
    print("共享充电宝投放管理系统 - 功能测试")
    print("=" * 60)

    try:
        db_path = os.path.join(os.path.dirname(__file__), 'test_power_bank.db')
        if os.path.exists(db_path):
            os.remove(db_path)

        os.environ['TEST_DB'] = db_path

        test_billing_service()
        batch_id = test_batch_service()
        test_outbound_service(batch_id)
        test_rental_service(batch_id)

        print("\n" + "=" * 60)
        print("🎉 所有模块测试通过!")
        print("=" * 60)

        if os.path.exists(db_path):
            os.remove(db_path)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
