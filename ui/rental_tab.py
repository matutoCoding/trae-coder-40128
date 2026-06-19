import csv
import os
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                             QPushButton, QDialog, QFormLayout, QLineEdit, QSpinBox,
                             QMessageBox, QHeaderView, QLabel, QGroupBox,
                             QDialogButtonBox, QDateEdit, QComboBox, QTabWidget,
                             QDoubleSpinBox, QTextEdit, QFileDialog)
from PyQt5.QtCore import Qt, QDate
from services.rental_service import RentalService
from services.batch_service import BatchService
from services.dashboard_service import DashboardService


class ReturnDialog(QDialog):
    def __init__(self, parent=None, order=None):
        super().__init__(parent)
        self.setWindowTitle("归还设备")
        self.setMinimumWidth(400)
        self.order = order

        layout = QFormLayout(self)

        if order:
            layout.addRow("设备编号:", QLabel(order.get('device_no', '')))
            layout.addRow("网点:", QLabel(order.get('outlet_name', '')))
            layout.addRow("借出时间:", QLabel(order.get('borrow_time', '')))

        self.return_date_edit = QDateEdit()
        self.return_date_edit.setCalendarPopup(True)
        self.return_date_edit.setDate(QDate.currentDate())
        self.return_date_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")

        self.hours_spin = QSpinBox()
        self.hours_spin.setRange(0, 72)
        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(0, 59)

        now = datetime.now()
        self.hours_spin.setValue(now.hour)
        self.minutes_spin.setValue(now.minute)

        time_layout = QHBoxLayout()
        time_layout.addWidget(self.hours_spin)
        time_layout.addWidget(QLabel("时"))
        time_layout.addWidget(self.minutes_spin)
        time_layout.addWidget(QLabel("分"))
        time_layout.addStretch()

        layout.addRow("归还日期:", self.return_date_edit)
        layout.addRow("归还时间:", time_layout)

        self.preview_label = QLabel("")
        self.preview_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c7be5;")
        layout.addRow("预计费用:", self.preview_label)

        self.calc_btn = QPushButton("预览费用")
        self.calc_btn.clicked.connect(self.preview_fee)
        layout.addRow(self.calc_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_return_time(self):
        date = self.return_date_edit.date().toString("yyyy-MM-dd")
        hours = str(self.hours_spin.value()).zfill(2)
        minutes = str(self.minutes_spin.value()).zfill(2)
        return f"{date} {hours}:{minutes}:00"

    def preview_fee(self):
        if self.order and hasattr(self.parent(), 'rental_service'):
            try:
                return_time = self.get_return_time()
                borrow_time = self.order['borrow_time']
                result = self.parent().rental_service.billing_service.calculate_rental_fee(
                    borrow_time, return_time, self.order['billing_rule_id']
                )
                self.preview_label.setText(
                    f"时长: {result['duration_minutes']}分钟 | "
                    f"费用: <span style='color: #e74c3c;'>{result['final_amount']:.2f}</span>元"
                )
                self.preview_label.setTextFormat(Qt.RichText)
            except Exception as e:
                self.preview_label.setText(f"计算失败: {str(e)}")


class RentalTab(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.rental_service = RentalService(db)
        self.batch_service = BatchService(db)
        self.dashboard_service = DashboardService(db)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        summary_group = QGroupBox("运营概览")
        summary_layout = QHBoxLayout(summary_group)
        self.summary_labels = {}
        summary_items = [
            ('total_orders', '总订单'),
            ('completed_orders', '已完成'),
            ('active_orders', '进行中'),
            ('total_revenue', '总营收'),
            ('avg_amount', '平均金额'),
            ('avg_duration', '平均时长')
        ]
        for key, label in summary_items:
            item_layout = QVBoxLayout()
            self.summary_labels[key] = QLabel("0")
            self.summary_labels[key].setStyleSheet("font-size: 16px; font-weight: bold; color: #2c7be5;")
            item_layout.addWidget(self.summary_labels[key])
            item_layout.addWidget(QLabel(label))
            summary_layout.addLayout(item_layout)
        main_layout.addWidget(summary_group)

        self.tab_widget = QTabWidget()

        orders_page = QWidget()
        orders_layout = QVBoxLayout(orders_page)

        order_button_layout = QHBoxLayout()
        self.borrow_btn = QPushButton("借出设备")
        self.borrow_btn.clicked.connect(self.borrow_device)
        self.return_btn = QPushButton("归还设备")
        self.return_btn.clicked.connect(self.return_device)
        self.view_order_btn = QPushButton("查看订单")
        self.view_order_btn.clicked.connect(self.view_order)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.load_data)

        order_button_layout.addWidget(self.borrow_btn)
        order_button_layout.addWidget(self.return_btn)
        order_button_layout.addWidget(self.view_order_btn)
        order_button_layout.addStretch()
        order_button_layout.addWidget(self.refresh_btn)
        orders_layout.addLayout(order_button_layout)

        order_tab_widget = QTabWidget()

        active_page = QWidget()
        active_layout = QVBoxLayout(active_page)
        self.active_table = QTableWidget()
        self.active_table.setColumnCount(7)
        self.active_table.setHorizontalHeaderLabels([
            "订单号", "设备编号", "网点", "借出时间", "规则", "时长", "状态"
        ])
        self.active_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.active_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.active_table.setEditTriggers(QTableWidget.NoEditTriggers)
        active_layout.addWidget(self.active_table)

        completed_page = QWidget()
        completed_layout = QVBoxLayout(completed_page)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("开始日期:"))
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate.currentDate().addDays(-30))
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        filter_layout.addWidget(self.start_date_edit)
        filter_layout.addWidget(QLabel("结束日期:"))
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(QDate.currentDate())
        self.end_date_edit.setDisplayFormat("yyyy-MM-dd")
        filter_layout.addWidget(self.end_date_edit)
        self.filter_btn = QPushButton("筛选")
        self.filter_btn.clicked.connect(self.load_completed_orders)
        filter_layout.addWidget(self.filter_btn)
        filter_layout.addStretch()
        completed_layout.addLayout(filter_layout)

        self.completed_table = QTableWidget()
        self.completed_table.setColumnCount(9)
        self.completed_table.setHorizontalHeaderLabels([
            "订单号", "设备编号", "网点", "借出时间", "归还时间", "时长(分)", "金额", "规则", "状态"
        ])
        self.completed_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.completed_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.completed_table.setEditTriggers(QTableWidget.NoEditTriggers)
        completed_layout.addWidget(self.completed_table)

        order_tab_widget.addTab(active_page, "进行中")
        order_tab_widget.addTab(completed_page, "已完成")
        orders_layout.addWidget(order_tab_widget)

        bills_page = QWidget()
        bills_layout = QVBoxLayout(bills_page)

        bill_button_layout = QHBoxLayout()
        self.generate_bill_btn = QPushButton("生成日账单")
        self.generate_bill_btn.clicked.connect(self.generate_bill)
        self.view_bill_btn = QPushButton("查看账单")
        self.view_bill_btn.clicked.connect(self.view_bill)
        bill_button_layout.addWidget(self.generate_bill_btn)
        bill_button_layout.addWidget(self.view_bill_btn)
        bill_button_layout.addStretch()
        bills_layout.addLayout(bill_button_layout)

        self.bills_table = QTableWidget()
        self.bills_table.setColumnCount(6)
        self.bills_table.setHorizontalHeaderLabels([
            "账单号", "账单日期", "订单数", "总金额", "状态", "创建时间"
        ])
        self.bills_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.bills_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.bills_table.setEditTriggers(QTableWidget.NoEditTriggers)
        bills_layout.addWidget(self.bills_table)

        faulty_page = QWidget()
        faulty_layout = QVBoxLayout(faulty_page)

        faulty_button_layout = QHBoxLayout()
        self.lock_btn = QPushButton("锁定下架")
        self.lock_btn.clicked.connect(self.lock_device)
        self.unlock_btn = QPushButton("解锁恢复")
        self.unlock_btn.clicked.connect(self.unlock_device)
        self.refresh_faulty_btn = QPushButton("刷新")
        self.refresh_faulty_btn.clicked.connect(self.load_faulty_devices)
        faulty_button_layout.addWidget(self.lock_btn)
        faulty_button_layout.addWidget(self.unlock_btn)
        faulty_button_layout.addStretch()
        faulty_button_layout.addWidget(self.refresh_faulty_btn)
        faulty_layout.addLayout(faulty_button_layout)

        self.faulty_table = QTableWidget()
        self.faulty_table.setColumnCount(6)
        self.faulty_table.setHorizontalHeaderLabels([
            "设备编号", "批次号", "当前网点", "状态", "最后操作", "更新时间"
        ])
        self.faulty_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.faulty_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.faulty_table.setEditTriggers(QTableWidget.NoEditTriggers)
        faulty_layout.addWidget(self.faulty_table)

        report_page = QWidget()
        report_page_layout = QVBoxLayout(report_page)

        report_sub_tab = QTabWidget()

        report_content_page = QWidget()
        report_layout = QVBoxLayout(report_content_page)

        report_filter_layout = QHBoxLayout()
        report_filter_layout.addWidget(QLabel("开始日期:"))
        self.report_start_date = QDateEdit()
        self.report_start_date.setCalendarPopup(True)
        self.report_start_date.setDate(QDate.currentDate().addDays(-30))
        self.report_start_date.setDisplayFormat("yyyy-MM-dd")
        report_filter_layout.addWidget(self.report_start_date)
        report_filter_layout.addWidget(QLabel("结束日期:"))
        self.report_end_date = QDateEdit()
        self.report_end_date.setCalendarPopup(True)
        self.report_end_date.setDate(QDate.currentDate())
        self.report_end_date.setDisplayFormat("yyyy-MM-dd")
        report_filter_layout.addWidget(self.report_end_date)
        self.generate_report_btn = QPushButton("📊 生成营收报表")
        self.generate_report_btn.clicked.connect(self.generate_revenue_report)
        report_filter_layout.addWidget(self.generate_report_btn)
        self.view_outlet_orders_btn = QPushButton("📋 查看网点订单明细")
        self.view_outlet_orders_btn.clicked.connect(self.view_outlet_order_detail)
        report_filter_layout.addWidget(self.view_outlet_orders_btn)
        self.export_summary_btn = QPushButton("📤 导出网点汇总CSV")
        self.export_summary_btn.clicked.connect(self.export_report_summary_csv)
        report_filter_layout.addWidget(self.export_summary_btn)
        self.export_orders_btn = QPushButton("📤 导出订单明细CSV")
        self.export_orders_btn.clicked.connect(self.export_report_orders_csv)
        report_filter_layout.addWidget(self.export_orders_btn)
        report_filter_layout.addStretch()
        report_layout.addLayout(report_filter_layout)

        self.report_summary_group = QGroupBox("汇总数据")
        self.report_summary_labels = {}
        summary_items = [
            ('outlet_count', '涉及网点'),
            ('total_orders', '总订单'),
            ('completed_orders', '已完成'),
            ('total_revenue', '总营收'),
            ('avg_amount', '平均客单价'),
            ('avg_duration', '平均时长')
        ]
        rsum_layout = QHBoxLayout(self.report_summary_group)
        for key, label in summary_items:
            item_layout = QVBoxLayout()
            self.report_summary_labels[key] = QLabel("0")
            self.report_summary_labels[key].setStyleSheet("font-size: 16px; font-weight: bold; color: #2c7be5;")
            item_layout.addWidget(self.report_summary_labels[key])
            item_layout.addWidget(QLabel(label))
            rsum_layout.addLayout(item_layout)
        report_layout.addWidget(self.report_summary_group)

        self.report_table = QTableWidget()
        self.report_table.setColumnCount(9)
        self.report_table.setHorizontalHeaderLabels([
            "网点ID", "网点名称", "类型", "订单数", "已完成", "进行中",
            "营收(元)", "平均金额(元)", "平均时长(分)"
        ])
        self.report_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.report_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.report_table.setEditTriggers(QTableWidget.NoEditTriggers)
        report_layout.addWidget(self.report_table, 1)

        type_group = QGroupBox("按网点类型汇总")
        type_layout = QHBoxLayout(type_group)
        self.location_type_table = QTableWidget()
        self.location_type_table.setColumnCount(5)
        self.location_type_table.setHorizontalHeaderLabels([
            "网点类型", "网点数", "订单数", "营收(元)", "平均金额(元)"
        ])
        self.location_type_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.location_type_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.location_type_table.setMaximumHeight(150)
        type_layout.addWidget(self.location_type_table)
        report_layout.addWidget(type_group)

        report_sub_tab.addTab(report_content_page, "📊 报表")

        reconciliation_page = QWidget()
        reconciliation_layout = QVBoxLayout(reconciliation_page)

        reconciliation_btn_layout = QHBoxLayout()
        self.generate_reconciliation_btn = QPushButton("🔄 生成对账数据")
        self.generate_reconciliation_btn.clicked.connect(self.generate_reconciliation_data)
        reconciliation_btn_layout.addWidget(self.generate_reconciliation_btn)
        reconciliation_btn_layout.addStretch()
        reconciliation_layout.addLayout(reconciliation_btn_layout)

        self.recon_summary_group = QGroupBox("汇总对比")
        recon_summary_grid = QVBoxLayout(self.recon_summary_group)
        recon_header = QHBoxLayout()
        recon_header.addWidget(QLabel(""))
        recon_header.addWidget(QLabel("订单数"))
        recon_header.addWidget(QLabel("营收(元)"))
        recon_summary_grid.addLayout(recon_header)

        report_row = QHBoxLayout()
        report_row.addWidget(QLabel("报表口径(含进行中)"))
        self.recon_report_orders_label = QLabel("0")
        self.recon_report_orders_label.setStyleSheet("font-weight: bold; color: #2c7be5;")
        report_row.addWidget(self.recon_report_orders_label)
        self.recon_report_revenue_label = QLabel("0.00")
        self.recon_report_revenue_label.setStyleSheet("font-weight: bold; color: #2c7be5;")
        report_row.addWidget(self.recon_report_revenue_label)
        recon_summary_grid.addLayout(report_row)

        completed_row = QHBoxLayout()
        completed_row.addWidget(QLabel("已完成口径"))
        self.recon_completed_orders_label = QLabel("0")
        self.recon_completed_orders_label.setStyleSheet("font-weight: bold; color: #27ae60;")
        completed_row.addWidget(self.recon_completed_orders_label)
        self.recon_completed_revenue_label = QLabel("0.00")
        self.recon_completed_revenue_label.setStyleSheet("font-weight: bold; color: #27ae60;")
        completed_row.addWidget(self.recon_completed_revenue_label)
        recon_summary_grid.addLayout(completed_row)

        diff_row = QHBoxLayout()
        diff_row.addWidget(QLabel("差异(进行中订单)"))
        self.recon_diff_orders_label = QLabel("0")
        self.recon_diff_orders_label.setStyleSheet("font-weight: bold; color: #e74c3c;")
        diff_row.addWidget(self.recon_diff_orders_label)
        self.recon_diff_revenue_label = QLabel("0.00")
        self.recon_diff_revenue_label.setStyleSheet("font-weight: bold; color: #e74c3c; background-color: #fff3cd; padding: 2px;")
        diff_row.addWidget(self.recon_diff_revenue_label)
        recon_summary_grid.addLayout(diff_row)

        reconciliation_layout.addWidget(self.recon_summary_group)

        self.recon_table = QTableWidget()
        self.recon_table.setColumnCount(7)
        self.recon_table.setHorizontalHeaderLabels([
            "网点名称", "报表订单数", "已完成订单数", "订单差异",
            "报表营收", "已完成营收", "营收差异"
        ])
        self.recon_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.recon_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.recon_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.recon_table.doubleClicked.connect(self._recon_table_double_clicked)
        reconciliation_layout.addWidget(self.recon_table, 1)

        self.recon_conclusion_label = QLabel("")
        self.recon_conclusion_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px;")
        reconciliation_layout.addWidget(self.recon_conclusion_label)

        report_sub_tab.addTab(reconciliation_page, "🔍 对账核对")

        report_page_layout.addWidget(report_sub_tab)

        self.tab_widget.addTab(orders_page, "租借订单")
        self.tab_widget.addTab(bills_page, "账单管理")
        self.tab_widget.addTab(report_page, "📊 营收报表")
        self.tab_widget.addTab(faulty_page, "坏宝管理")

        main_layout.addWidget(self.tab_widget, 1)

    def load_data(self):
        self.load_summary()
        self.load_active_orders()
        self.load_completed_orders()
        self.load_bills()
        self.load_faulty_devices()

    def load_summary(self):
        summary = self.rental_service.get_rental_summary()
        for key, label in self.summary_labels.items():
            value = summary.get(key, 0) or 0
            if isinstance(value, float):
                if key == 'avg_duration':
                    label.setText(f"{value:.0f} 分")
                else:
                    label.setText(f"{value:.2f} 元")
            else:
                label.setText(str(value))

    def load_active_orders(self):
        orders = self.rental_service.get_active_orders()
        self.active_table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            self.active_table.setItem(row, 0, QTableWidgetItem(order['order_no']))
            self.active_table.setItem(row, 1, QTableWidgetItem(order['device_no']))
            self.active_table.setItem(row, 2, QTableWidgetItem(order['outlet_name']))
            self.active_table.setItem(row, 3, QTableWidgetItem(order['borrow_time']))
            self.active_table.setItem(row, 4, QTableWidgetItem(order['rule_name']))

            try:
                borrow = datetime.strptime(order['borrow_time'], '%Y-%m-%d %H:%M:%S')
                now = datetime.now()
                duration = int((now - borrow).total_seconds() / 60)
                self.active_table.setItem(row, 5, QTableWidgetItem(f"{duration} 分钟"))
            except:
                self.active_table.setItem(row, 5, QTableWidgetItem("-"))

            status_item = QTableWidgetItem("使用中")
            status_item.setForeground(Qt.darkYellow)
            self.active_table.setItem(row, 6, status_item)

    def load_completed_orders(self):
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")
        orders = self.rental_service.get_completed_orders(start_date, end_date)
        self.completed_table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            self.completed_table.setItem(row, 0, QTableWidgetItem(order['order_no']))
            self.completed_table.setItem(row, 1, QTableWidgetItem(order['device_no']))
            self.completed_table.setItem(row, 2, QTableWidgetItem(order['outlet_name']))
            self.completed_table.setItem(row, 3, QTableWidgetItem(order['borrow_time']))
            self.completed_table.setItem(row, 4, QTableWidgetItem(order['return_time']))
            self.completed_table.setItem(row, 5, QTableWidgetItem(str(order['duration_minutes'])))
            amount_item = QTableWidgetItem(f"{order['final_amount']:.2f}")
            amount_item.setForeground(Qt.red)
            self.completed_table.setItem(row, 6, amount_item)
            self.completed_table.setItem(row, 7, QTableWidgetItem(order['rule_name']))
            status_item = QTableWidgetItem("已完成")
            status_item.setForeground(Qt.green)
            self.completed_table.setItem(row, 8, status_item)

        self.load_summary()

    def load_bills(self):
        bills = self.rental_service.get_all_bills()
        self.bills_table.setRowCount(len(bills))
        for row, bill in enumerate(bills):
            self.bills_table.setItem(row, 0, QTableWidgetItem(bill['bill_no']))
            self.bills_table.setItem(row, 1, QTableWidgetItem(bill['bill_date']))
            self.bills_table.setItem(row, 2, QTableWidgetItem(str(bill['order_count'])))
            amount_item = QTableWidgetItem(f"{bill['total_amount']:.2f}")
            amount_item.setForeground(Qt.red)
            self.bills_table.setItem(row, 3, amount_item)
            status_map = {'unsettled': ('未结算', Qt.blue), 'settled': ('已结算', Qt.green)}
            status_text, status_color = status_map.get(bill['status'], (bill['status'], Qt.black))
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(status_color)
            self.bills_table.setItem(row, 4, status_item)
            self.bills_table.setItem(row, 5, QTableWidgetItem(bill['created_at']))

    def load_faulty_devices(self):
        devices = self.rental_service.get_faulty_devices()
        self.faulty_table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            self.faulty_table.setItem(row, 0, QTableWidgetItem(device['device_no']))
            self.faulty_table.setItem(row, 1, QTableWidgetItem(device['batch_no']))
            self.faulty_table.setItem(row, 2, QTableWidgetItem(device.get('outlet_name') or '-'))
            status_item = QTableWidgetItem("故障锁定")
            status_item.setForeground(Qt.red)
            self.faulty_table.setItem(row, 3, status_item)
            self.faulty_table.setItem(row, 4, QTableWidgetItem(device.get('last_maintenance') or '-'))
            self.faulty_table.setItem(row, 5, QTableWidgetItem(device['updated_at']))

    def borrow_device(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("借出设备")
        dialog.setMinimumWidth(400)
        layout = QFormLayout(dialog)

        outlet_combo = QComboBox()
        outlets = self.batch_service.get_all_outlets()
        for outlet in outlets:
            outlet_combo.addItem(outlet['name'], outlet['id'])
        layout.addRow("选择网点:", outlet_combo)

        device_combo = QComboBox()

        def update_devices(outlet_id):
            devices = self.rental_service.get_available_devices_for_rent(outlet_id)
            device_combo.clear()
            for device in devices:
                device_combo.addItem(device['device_no'], device['id'])

        outlet_combo.currentIndexChanged.connect(lambda idx: update_devices(outlet_combo.currentData()))
        if outlets:
            update_devices(outlets[0]['id'])

        layout.addRow("选择设备:", device_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() == QDialog.Accepted:
            device_id = device_combo.currentData()
            outlet_id = outlet_combo.currentData()
            if not device_id:
                QMessageBox.warning(self, "警告", "该网点没有可用设备")
                return
            try:
                order_id = self.rental_service.borrow_device(device_id, outlet_id)
                self.load_data()
                QMessageBox.information(self, "成功", f"设备借出成功!\n订单ID: {order_id}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"借出失败: {str(e)}")

    def return_device(self):
        current_row = self.active_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请从进行中订单列表选择要归还的设备")
            return

        order_no = self.active_table.item(current_row, 0).text()
        active_orders = self.rental_service.get_active_orders()
        order = next((o for o in active_orders if o['order_no'] == order_no), None)

        if order:
            dialog = ReturnDialog(self, order)
            dialog.rental_service = self.rental_service
            if dialog.exec_() == QDialog.Accepted:
                try:
                    return_time = dialog.get_return_time()
                    result = self.rental_service.return_device(order['device_id'], return_time)
                    self.load_data()
                    fee = result['fee']
                    QMessageBox.information(self, "成功",
                        f"设备归还成功!\n"
                        f"时长: {fee['duration_minutes']}分钟\n"
                        f"费用: {fee['final_amount']:.2f}元")
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"归还失败: {str(e)}")

    def view_order(self):
        current_widget = self.tab_widget.currentWidget()
        if current_widget is None:
            return

        current_index = self.tab_widget.indexOf(current_widget)
        if current_index == 0:
            order_tab = self.tab_widget.widget(0).findChild(QTabWidget)
            if order_tab:
                current_order_tab = order_tab.currentWidget()
                if current_order_tab == order_tab.widget(0):
                    table = self.active_table
                else:
                    table = self.completed_table
                current_row = table.currentRow()
                if current_row < 0:
                    QMessageBox.warning(self, "警告", "请选择要查看的订单")
                    return
                order_no = table.item(current_row, 0).text()
                orders = self.rental_service.get_active_orders() + self.rental_service.get_completed_orders()
                order = next((o for o in orders if o['order_no'] == order_no), None)
                if order:
                    QMessageBox.information(self, "订单详情",
                        f"订单号: {order['order_no']}\n"
                        f"设备: {order['device_no']}\n"
                        f"网点: {order['outlet_name']}\n"
                        f"借出时间: {order['borrow_time']}\n"
                        f"归还时间: {order.get('return_time') or '- '}\n"
                        f"时长: {order.get('duration_minutes') or '- '}分钟\n"
                        f"金额: {order.get('final_amount') or '- '}元")

    def generate_bill(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("生成日账单")
        dialog.setMinimumWidth(300)
        layout = QFormLayout(dialog)

        bill_date_edit = QDateEdit()
        bill_date_edit.setCalendarPopup(True)
        bill_date_edit.setDate(QDate.currentDate().addDays(-1))
        bill_date_edit.setDisplayFormat("yyyy-MM-dd")
        layout.addRow("账单日期:", bill_date_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() == QDialog.Accepted:
            bill_date = bill_date_edit.date().toString("yyyy-MM-dd")
            try:
                result = self.rental_service.generate_daily_bill(bill_date)
                if result:
                    self.load_bills()
                    QMessageBox.information(self, "成功",
                        f"账单生成成功!\n"
                        f"账单号: {result['bill_no']}\n"
                        f"订单数: {result['order_count']}\n"
                        f"总金额: {result['total_amount']:.2f}元")
                else:
                    QMessageBox.information(self, "提示", "该日期没有可生成账单的订单")
            except ValueError as e:
                QMessageBox.warning(self, "警告", str(e))
            except Exception as e:
                QMessageBox.critical(self, "错误", f"生成失败: {str(e)}")

    def view_bill(self):
        current_row = self.bills_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要查看的账单")
            return

        bill_no = self.bills_table.item(current_row, 0).text()
        bills = self.rental_service.get_all_bills()
        bill = next((b for b in bills if b['bill_no'] == bill_no), None)

        if bill:
            bill_detail = self.rental_service.get_bill_by_id(bill['id'])
            dialog = QDialog(self)
            dialog.setWindowTitle(f"账单详情 - {bill_no}")
            dialog.setMinimumSize(900, 600)
            layout = QVBoxLayout(dialog)

            info_layout = QHBoxLayout()
            info_layout.addWidget(QLabel(f"<b>账单号:</b> {bill_no}"))
            info_layout.addWidget(QLabel(f"<b>日期:</b> {bill['bill_date']}"))
            info_layout.addWidget(QLabel(f"<b>订单数:</b> {bill['order_count']}"))
            info_layout.addWidget(QLabel(f"<b>总金额:</b> <span style='color: red;'>{bill['total_amount']:.2f}</span>元"))
            info_layout.addStretch()
            layout.addLayout(info_layout)

            item_table = QTableWidget()
            item_table.setColumnCount(6)
            item_table.setHorizontalHeaderLabels([
                "设备编号", "网点", "借出时间", "归还时间", "时长(分)", "金额"
            ])
            item_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            item_table.setEditTriggers(QTableWidget.NoEditTriggers)
            items = bill_detail.get('items', [])
            item_table.setRowCount(len(items))
            for row, item in enumerate(items):
                item_table.setItem(row, 0, QTableWidgetItem(item['device_no']))
                item_table.setItem(row, 1, QTableWidgetItem(item['outlet_name']))
                item_table.setItem(row, 2, QTableWidgetItem(item['borrow_time']))
                item_table.setItem(row, 3, QTableWidgetItem(item['return_time']))
                item_table.setItem(row, 4, QTableWidgetItem(str(item['duration_minutes'])))
                amount_item = QTableWidgetItem(f"{item['amount']:.2f}")
                amount_item.setForeground(Qt.red)
                item_table.setItem(row, 5, amount_item)
            layout.addWidget(item_table)

            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            dialog.exec_()

    def lock_device(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("锁定坏宝")
        dialog.setMinimumWidth(400)
        layout = QFormLayout(dialog)

        device_no_edit = QLineEdit()
        layout.addRow("设备编号:", device_no_edit)

        desc_edit = QTextEdit()
        desc_edit.setMaximumHeight(80)
        layout.addRow("故障描述:", desc_edit)

        operator_edit = QLineEdit()
        layout.addRow("操作员:", operator_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() == QDialog.Accepted:
            device_no = device_no_edit.text().strip()
            description = desc_edit.toPlainText().strip()
            operator = operator_edit.text().strip()

            if not device_no:
                QMessageBox.warning(self, "警告", "请输入设备编号")
                return

            try:
                device = self.db.query_one("SELECT * FROM devices WHERE device_no = ?", (device_no,))
                if not device:
                    QMessageBox.warning(self, "警告", "设备不存在")
                    return

                self.rental_service.mark_device_faulty(device['id'], description or None, operator or None)
                self.load_data()
                QMessageBox.information(self, "成功", "设备已锁定下架")
            except ValueError as e:
                QMessageBox.warning(self, "警告", str(e))
            except Exception as e:
                QMessageBox.critical(self, "错误", f"锁定失败: {str(e)}")

    def unlock_device(self):
        current_row = self.faulty_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请从故障列表选择要解锁的设备")
            return

        device_no = self.faulty_table.item(current_row, 0).text()
        if QMessageBox.question(self, "确认", f"确定要解锁设备 {device_no} 吗?",
                                 QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                device = self.db.query_one("SELECT * FROM devices WHERE device_no = ?", (device_no,))
                if device:
                    self.rental_service.unlock_device(device['id'], "修复完成", "管理员")
                    self.load_data()
                    QMessageBox.information(self, "成功", "设备已解锁恢复")
            except ValueError as e:
                QMessageBox.warning(self, "警告", str(e))
            except Exception as e:
                QMessageBox.critical(self, "错误", f"解锁失败: {str(e)}")

    def generate_revenue_report(self):
        start_date = self.report_start_date.date().toString("yyyy-MM-dd")
        end_date = self.report_end_date.date().toString("yyyy-MM-dd")

        try:
            report_data = self.rental_service.get_revenue_report_by_outlet(start_date, end_date)
            summary = self.rental_service.get_revenue_report_summary(start_date, end_date)
            loc_type_data = self.rental_service.get_revenue_by_location_type(start_date, end_date)

            if summary:
                for key, label in self.report_summary_labels.items():
                    value = summary.get(key, 0) or 0
                    if isinstance(value, float):
                        if key == 'avg_duration':
                            label.setText(f"{value:.0f} 分")
                        else:
                            label.setText(f"{value:.2f} 元")
                    else:
                        label.setText(str(value))

            self.report_table.setRowCount(len(report_data))
            for row, data in enumerate(report_data):
                self.report_table.setItem(row, 0, QTableWidgetItem(str(data['outlet_id'])))
                self.report_table.setItem(row, 1, QTableWidgetItem(data['outlet_name']))
                self.report_table.setItem(row, 2, QTableWidgetItem(data.get('location_type', '-')))
                self.report_table.setItem(row, 3, QTableWidgetItem(str(data['order_count'])))
                self.report_table.setItem(row, 4, QTableWidgetItem(str(data['completed_count'])))
                self.report_table.setItem(row, 5, QTableWidgetItem(str(data['active_count'])))

                revenue_item = QTableWidgetItem(f"{data['total_revenue']:.2f}")
                revenue_item.setForeground(Qt.red)
                self.report_table.setItem(row, 6, revenue_item)

                self.report_table.setItem(row, 7, QTableWidgetItem(f"{data['avg_amount']:.2f}"))
                self.report_table.setItem(row, 8, QTableWidgetItem(f"{data['avg_duration']:.0f}"))

            self.location_type_table.setRowCount(len(loc_type_data))
            for row, data in enumerate(loc_type_data):
                self.location_type_table.setItem(row, 0, QTableWidgetItem(data.get('location_type') or '其他'))
                self.location_type_table.setItem(row, 1, QTableWidgetItem(str(data['outlet_count'])))
                self.location_type_table.setItem(row, 2, QTableWidgetItem(str(data['order_count'])))

                revenue_item = QTableWidgetItem(f"{data['total_revenue']:.2f}")
                revenue_item.setForeground(Qt.red)
                self.location_type_table.setItem(row, 3, revenue_item)
                self.location_type_table.setItem(row, 4, QTableWidgetItem(f"{data['avg_amount']:.2f}"))

            QMessageBox.information(self, "成功",
                f"报表生成完成!\n涉及网点: {summary.get('outlet_count',0)}个\n"
                f"订单数: {summary.get('total_orders',0)}笔\n"
                f"总营收: {summary.get('total_revenue',0):.2f}元")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成报表失败: {str(e)}")

    def view_outlet_order_detail(self):
        current_row = self.report_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请从营收报表中选择要查看的网点")
            return

        start_date = self.report_start_date.date().toString("yyyy-MM-dd")
        end_date = self.report_end_date.date().toString("yyyy-MM-dd")
        outlet_id = int(self.report_table.item(current_row, 0).text())
        outlet_name = self.report_table.item(current_row, 1).text()

        try:
            orders = self.rental_service.get_outlet_orders_detail(outlet_id, start_date, end_date)

            dialog = QDialog(self)
            dialog.setWindowTitle(f"网点订单明细 - {outlet_name}")
            dialog.setMinimumSize(1100, 700)
            layout = QVBoxLayout(dialog)

            info_layout = QHBoxLayout()
            info_layout.addWidget(QLabel(f"<b>网点:</b> {outlet_name}"))
            info_layout.addWidget(QLabel(f"<b>时间范围:</b> {start_date} 至 {end_date}"))
            info_layout.addWidget(QLabel(f"<b>订单数:</b> {len(orders)}"))
            total_rev = sum(o['final_amount'] for o in orders if o.get('final_amount'))
            info_layout.addWidget(QLabel(f"<b>总营收:</b> <span style='color: red;'>{total_rev:.2f}</span> 元"))
            info_layout.addStretch()
            layout.addLayout(info_layout)

            table = QTableWidget()
            table.setColumnCount(9)
            table.setHorizontalHeaderLabels([
                "订单号", "设备编号", "规则", "借出时间", "归还时间",
                "时长(分)", "计算金额", "实付金额", "封顶天数"
            ])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setRowCount(len(orders))
            for row, order in enumerate(orders):
                table.setItem(row, 0, QTableWidgetItem(order['order_no']))
                table.setItem(row, 1, QTableWidgetItem(order['device_no']))
                table.setItem(row, 2, QTableWidgetItem(order.get('rule_name', '-')))
                table.setItem(row, 3, QTableWidgetItem(order['borrow_time']))
                table.setItem(row, 4, QTableWidgetItem(order.get('return_time', '-')))
                table.setItem(row, 5, QTableWidgetItem(str(order.get('duration_minutes') or '-')))
                if order.get('calculated_amount') is not None:
                    table.setItem(row, 6, QTableWidgetItem(f"{order['calculated_amount']:.2f}"))
                else:
                    table.setItem(row, 6, QTableWidgetItem('-'))
                final_item = QTableWidgetItem(f"{order['final_amount']:.2f}")
                final_item.setForeground(Qt.red)
                table.setItem(row, 7, final_item)
                if order.get('duration_minutes'):
                    days = (order['duration_minutes'] - 1) // 1440 + 1
                    table.setItem(row, 8, QTableWidgetItem(f"{days}天"))
                else:
                    table.setItem(row, 8, QTableWidgetItem('-'))
            layout.addWidget(table, 1)

            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"查询失败: {str(e)}")

    def _get_report_filter(self):
        start_date = self.report_start_date.date().toString("yyyy-MM-dd")
        end_date = self.report_end_date.date().toString("yyyy-MM-dd")
        return start_date, end_date

    def export_report_summary_csv(self):
        start_date, end_date = self._get_report_filter()
        try:
            report_data = self.rental_service.get_revenue_report_by_outlet(start_date, end_date)
            if not report_data:
                QMessageBox.warning(self, "提示", "当前筛选条件下没有数据可导出，请先生成报表")
                return

            default_name = f"营收报表_网点汇总_{start_date}_{end_date}.csv"
            save_path, _ = QFileDialog.getSaveFileName(
                self, "导出网点汇总CSV", default_name, "CSV文件 (*.csv)"
            )
            if not save_path:
                return

            with open(save_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "网点ID", "网点名称", "网点类型", "订单数", "已完成订单",
                    "进行中订单", "营收(元)", "平均金额(元)", "平均时长(分)"
                ])
                total_rev = 0
                total_orders = 0
                for row in report_data:
                    writer.writerow([
                        row.get('outlet_id', ''),
                        row.get('outlet_name', ''),
                        row.get('location_type', ''),
                        row.get('order_count', 0),
                        row.get('completed_count', 0),
                        row.get('active_count', 0),
                        f"{row.get('total_revenue', 0):.2f}",
                        f"{row.get('avg_amount', 0):.2f}",
                        f"{row.get('avg_duration', 0):.0f}"
                    ])
                    total_rev += row.get('total_revenue', 0) or 0
                    total_orders += row.get('order_count', 0) or 0
                writer.writerow([])
                writer.writerow(["合计", "", "", total_orders, "", "", f"{total_rev:.2f}", "", ""])

            QMessageBox.information(self, "成功",
                f"导出成功!\n文件: {save_path}\n"
                f"网点数: {len(report_data)} | 总订单: {total_orders} | 总营收: {total_rev:.2f}元")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")

    def export_report_orders_csv(self):
        start_date, end_date = self._get_report_filter()
        try:
            summary = self.rental_service.get_revenue_report_by_outlet(start_date, end_date)
            if not summary:
                QMessageBox.warning(self, "提示", "当前筛选条件下没有数据可导出，请先生成报表")
                return

            default_name = f"营收报表_订单明细_{start_date}_{end_date}.csv"
            save_path, _ = QFileDialog.getSaveFileName(
                self, "导出订单明细CSV", default_name, "CSV文件 (*.csv)"
            )
            if not save_path:
                return

            all_orders = []
            for outlet_row in summary:
                outlet_id = outlet_row.get('outlet_id')
                if outlet_id:
                    orders = self.rental_service.get_outlet_orders_detail(outlet_id, start_date, end_date)
                    all_orders.extend(orders)

            with open(save_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "订单号", "设备编号", "网点名称", "计费规则",
                    "借出时间", "归还时间", "时长(分)", "计算金额(元)",
                    "实收金额(元)", "封顶天数", "状态"
                ])
                total_amount = 0
                for order in all_orders:
                    duration = order.get('duration_minutes') or 0
                    days = (duration - 1) // 1440 + 1 if duration > 0 else 0
                    calc = order.get('calculated_amount')
                    if calc is None:
                        calc = order.get('final_amount', 0) or 0
                    final = order.get('final_amount', 0) or 0
                    total_amount += final
                    status = '进行中' if order.get('status') == 'active' else '已完成'
                    writer.writerow([
                        order.get('order_no', ''),
                        order.get('device_no', ''),
                        order.get('outlet_name', ''),
                        order.get('rule_name', ''),
                        order.get('borrow_time', ''),
                        order.get('return_time', ''),
                        duration,
                        f"{calc:.2f}",
                        f"{final:.2f}",
                        f"{days}天" if days > 0 else '-',
                        status
                    ])
                writer.writerow([])
                writer.writerow(["合计", "", f"{len(all_orders)}单", "", "", "", "", "", f"{total_amount:.2f}", "", ""])

            page_rev = sum(r.get('total_revenue', 0) or 0 for r in summary)
            QMessageBox.information(self, "成功",
                f"导出成功!\n文件: {save_path}\n"
                f"订单数: {len(all_orders)}笔 | 导出总营收: {total_amount:.2f}元\n"
                f"页面显示营收: {page_rev:.2f}元 | 核对: {'✅一致' if abs(total_amount - page_rev) < 0.01 else '⚠️存在差异'}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")

    def generate_reconciliation_data(self):
        start_date = self.report_start_date.date().toString("yyyy-MM-dd")
        end_date = self.report_end_date.date().toString("yyyy-MM-dd")

        try:
            data = self.dashboard_service.get_reconciliation_data(start_date, end_date)

            page_summary = data.get('page_summary', {})
            completed_only = data.get('completed_only', {})
            outlet_details = data.get('outlet_details', [])

            self.recon_report_orders_label.setText(str(page_summary.get('total_orders', 0)))
            self.recon_report_revenue_label.setText(f"{page_summary.get('total_revenue', 0):.2f}")

            self.recon_completed_orders_label.setText(str(completed_only.get('total_orders', 0)))
            self.recon_completed_revenue_label.setText(f"{completed_only.get('total_revenue', 0):.2f}")

            diff_orders = page_summary.get('total_orders', 0) - completed_only.get('total_orders', 0)
            diff_revenue = round(page_summary.get('total_revenue', 0) - completed_only.get('total_revenue', 0), 2)
            self.recon_diff_orders_label.setText(str(diff_orders))
            self.recon_diff_revenue_label.setText(f"{diff_revenue:.2f}")

            self.recon_table.setRowCount(len(outlet_details))
            diff_outlet_count = 0
            for row, detail in enumerate(outlet_details):
                self.recon_table.setItem(row, 0, QTableWidgetItem(detail['outlet_name']))
                self.recon_table.setItem(row, 1, QTableWidgetItem(str(detail['report_orders'])))
                self.recon_table.setItem(row, 2, QTableWidgetItem(str(detail['completed_orders'])))

                diff_o = detail['diff_orders']
                diff_o_item = QTableWidgetItem(str(diff_o))
                if diff_o != 0:
                    diff_o_item.setForeground(Qt.red)
                    diff_outlet_count += 1
                self.recon_table.setItem(row, 3, diff_o_item)

                report_rev_item = QTableWidgetItem(f"{detail['report_revenue']:.2f}")
                self.recon_table.setItem(row, 4, report_rev_item)

                completed_rev_item = QTableWidgetItem(f"{detail['completed_revenue']:.2f}")
                self.recon_table.setItem(row, 5, completed_rev_item)

                diff_r = detail['diff_revenue']
                diff_r_item = QTableWidgetItem(f"{diff_r:.2f}")
                if abs(diff_r) > 0.01:
                    diff_r_item.setForeground(Qt.red)
                self.recon_table.setItem(row, 6, diff_r_item)

            if diff_outlet_count == 0:
                self.recon_conclusion_label.setText("✅ 数据一致")
                self.recon_conclusion_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px; color: #27ae60;")
            else:
                self.recon_conclusion_label.setText(
                    f"⚠️ {diff_outlet_count}个网点存在进行中订单，导致差异{diff_revenue:.2f}元"
                )
                self.recon_conclusion_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px; color: #e74c3c; background-color: #fff3cd;")

            QMessageBox.information(self, "成功", "对账数据生成完成!")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成对账数据失败: {str(e)}")

    def _recon_table_double_clicked(self, index):
        row = index.row()
        outlet_name_item = self.recon_table.item(row, 0)
        if not outlet_name_item:
            return
        outlet_name = outlet_name_item.text()

        start_date = self.report_start_date.date().toString("yyyy-MM-dd")
        end_date = self.report_end_date.date().toString("yyyy-MM-dd")

        outlets = self.batch_service.get_all_outlets()
        outlet = next((o for o in outlets if o['name'] == outlet_name), None)
        if not outlet:
            QMessageBox.warning(self, "警告", f"未找到网点: {outlet_name}")
            return

        outlet_id = outlet['id']

        try:
            orders = self.rental_service.get_outlet_orders_detail(outlet_id, start_date, end_date)

            dialog = QDialog(self)
            dialog.setWindowTitle(f"网点订单明细 - {outlet_name}")
            dialog.setMinimumSize(1100, 700)
            layout = QVBoxLayout(dialog)

            info_layout = QHBoxLayout()
            info_layout.addWidget(QLabel(f"<b>网点:</b> {outlet_name}"))
            info_layout.addWidget(QLabel(f"<b>时间范围:</b> {start_date} 至 {end_date}"))
            info_layout.addWidget(QLabel(f"<b>订单数:</b> {len(orders)}"))
            total_rev = sum(o['final_amount'] for o in orders if o.get('final_amount'))
            info_layout.addWidget(QLabel(f"<b>总营收:</b> <span style='color: red;'>{total_rev:.2f}</span> 元"))
            info_layout.addStretch()
            layout.addLayout(info_layout)

            table = QTableWidget()
            table.setColumnCount(9)
            table.setHorizontalHeaderLabels([
                "订单号", "设备编号", "规则", "借出时间", "归还时间",
                "时长(分)", "计算金额", "实付金额", "封顶天数"
            ])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setRowCount(len(orders))
            for r, order in enumerate(orders):
                table.setItem(r, 0, QTableWidgetItem(order['order_no']))
                table.setItem(r, 1, QTableWidgetItem(order['device_no']))
                table.setItem(r, 2, QTableWidgetItem(order.get('rule_name', '-')))
                table.setItem(r, 3, QTableWidgetItem(order['borrow_time']))
                table.setItem(r, 4, QTableWidgetItem(order.get('return_time', '-')))
                table.setItem(r, 5, QTableWidgetItem(str(order.get('duration_minutes') or '-')))
                if order.get('calculated_amount') is not None:
                    table.setItem(r, 6, QTableWidgetItem(f"{order['calculated_amount']:.2f}"))
                else:
                    table.setItem(r, 6, QTableWidgetItem('-'))
                final_item = QTableWidgetItem(f"{order['final_amount']:.2f}")
                final_item.setForeground(Qt.red)
                table.setItem(r, 7, final_item)
                if order.get('duration_minutes'):
                    days = (order['duration_minutes'] - 1) // 1440 + 1
                    table.setItem(r, 8, QTableWidgetItem(f"{days}天"))
                else:
                    table.setItem(r, 8, QTableWidgetItem('-'))
            layout.addWidget(table, 1)

            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"查询失败: {str(e)}")
