from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                             QPushButton, QDialog, QFormLayout, QLineEdit, QSpinBox,
                             QMessageBox, QHeaderView, QLabel, QGroupBox,
                             QDialogButtonBox, QDateEdit, QTextEdit, QSplitter, QComboBox,
                             QTabWidget, QProgressBar, QListWidget, QListWidgetItem, QDoubleSpinBox)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QFont
from services.outbound_service import OutboundService
from services.batch_service import BatchService
from services.deployment_plan_service import DeploymentPlanService


class PlanDialog(QDialog):
    def __init__(self, parent=None, outlets_by_type=None):
        super().__init__(parent)
        self.setWindowTitle("新建投放计划")
        self.setMinimumWidth(550)
        self.outlets_by_type = outlets_by_type or {}

        layout = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如: 高铁站3月重点铺设计划")

        self.location_type_combo = QComboBox()
        all_types = list(set(self.outlets_by_type.keys()) | {'交通枢纽', '商业综合体', '写字楼', '医疗机构', '教育机构', '其他'})
        for t in sorted(all_types):
            self.location_type_combo.addItem(t, t)
        self.location_type_combo.currentIndexChanged.connect(self.update_outlet_list)

        self.target_total_spin = QSpinBox()
        self.target_total_spin.setRange(1, 100000)
        self.target_total_spin.setValue(100)

        self.priority_combo = QComboBox()
        self.priority_combo.addItem("一般", "normal")
        self.priority_combo.addItem("优先", "high")
        self.priority_combo.addItem("紧急", "urgent")

        self.plan_date_edit = QDateEdit()
        self.plan_date_edit.setCalendarPopup(True)
        self.plan_date_edit.setDate(QDate.currentDate())
        self.plan_date_edit.setDisplayFormat("yyyy-MM-dd")

        self.operator_edit = QLineEdit()
        self.remark_edit = QTextEdit()
        self.remark_edit.setMaximumHeight(60)

        layout.addRow("计划名称:", self.name_edit)
        layout.addRow("目标网点类型:", self.location_type_combo)
        layout.addRow("目标总数量:", self.target_total_spin)
        layout.addRow("优先级:", self.priority_combo)
        layout.addRow("计划日期:", self.plan_date_edit)
        layout.addRow("操作员:", self.operator_edit)

        outlets_group = QGroupBox("各网点分配目标 (拖动滑块或输入数量)")
        outlets_layout = QVBoxLayout(outlets_group)

        self.outlet_spins = {}
        self.outlet_list_widget = QWidget()
        self.outlet_list_layout = QVBoxLayout(self.outlet_list_widget)

        outlets_group.setLayout(outlets_layout)
        outlets_layout.addWidget(self.outlet_list_widget)
        self.update_outlet_list()

        self.total_allocated_label = QLabel("已分配: 0 / 目标: 0")
        self.total_allocated_label.setStyleSheet("font-weight: bold; color: #2c7be5;")
        outlets_layout.addWidget(self.total_allocated_label)

        layout.addRow(outlets_group)
        layout.addRow("备注:", self.remark_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.target_total_spin.valueChanged.connect(self.recalculate_allocation)

    def update_outlet_list(self):
        while self.outlet_list_layout.count():
            item = self.outlet_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        location_type = self.location_type_combo.currentData()
        outlets = self.outlets_by_type.get(location_type, [])

        self.outlet_spins = {}
        for outlet in outlets:
            row = QHBoxLayout()
            label = QLabel(f"{outlet['name']}")
            label.setMinimumWidth(200)
            row.addWidget(label)

            spin = QSpinBox()
            spin.setRange(0, 10000)
            spin.valueChanged.connect(self.recalculate_allocation)
            self.outlet_spins[outlet['id']] = spin
            row.addWidget(spin, 1)

            row.addWidget(QLabel("台"))
            self.outlet_list_layout.addLayout(row)

        if not outlets:
            self.outlet_list_layout.addWidget(QLabel("该类型下暂无网点"))

        self.recalculate_allocation()

    def recalculate_allocation(self):
        total = sum(spin.value() for spin in self.outlet_spins.values())
        target = self.target_total_spin.value()
        self.total_allocated_label.setText(f"已分配: {total} / 目标: {target}")
        if total > target:
            self.total_allocated_label.setStyleSheet("font-weight: bold; color: #e74c3c;")
        else:
            self.total_allocated_label.setStyleSheet("font-weight: bold; color: #27ae60;")

    def validate_and_accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "警告", "请输入计划名称")
            return
        total = sum(spin.value() for spin in self.outlet_spins.values())
        if total <= 0:
            QMessageBox.warning(self, "警告", "请至少分配一个网点的目标数量")
            return
        self.accept()

    def get_data(self):
        outlet_targets = [(outlet_id, spin.value())
                         for outlet_id, spin in self.outlet_spins.items() if spin.value() > 0]
        auto_targets = []
        target_total = self.target_total_spin.value()
        allocated = sum(q for _, q in outlet_targets)
        if allocated < target_total and outlet_targets:
            remaining = target_total - allocated
            avg_remaining = remaining // len(outlet_targets)
            remainder = remaining % len(outlet_targets)
            for i in range(len(outlet_targets)):
                add = avg_remaining + (1 if i < remainder else 0)
                outlet_targets[i] = (outlet_targets[i][0], outlet_targets[i][1] + add)

        return {
            'plan_name': self.name_edit.text().strip(),
            'location_type': self.location_type_combo.currentData(),
            'target_quantity': self.target_total_spin.value(),
            'outlet_targets': outlet_targets,
            'priority': self.priority_combo.currentData(),
            'plan_date': self.plan_date_edit.date().toString("yyyy-MM-dd"),
            'operator': self.operator_edit.text().strip() or None,
            'remark': self.remark_edit.toPlainText().strip() or None
        }


class PlanExecutionDialog(QDialog):
    def __init__(self, parent=None, plan=None, plan_service=None, batch_service=None):
        super().__init__(parent)
        self.setWindowTitle(f"执行投放计划 - {plan.get('plan_name', '')}")
        self.setMinimumWidth(500)
        self.plan = plan
        self.plan_service = plan_service
        self.batch_service = batch_service

        layout = QFormLayout(self)

        info_label = QLabel(f"计划号: {plan.get('plan_no', '')}<br>"
                          f"类型: {plan.get('location_type', '')}<br>"
                          f"目标: {plan.get('target_quantity', 0)} | 已完成: {plan.get('completed_quantity', 0)}")
        info_label.setTextFormat(Qt.RichText)
        info_label.setStyleSheet("padding: 8px; background: #f0f7ff; border-radius: 4px;")
        layout.addRow(info_label)

        self.plan_outlet_combo = QComboBox()
        for outlet in plan.get('outlets', []):
            remaining = outlet['target_quantity'] - outlet['completed_quantity']
            if remaining > 0:
                display = f"{outlet['outlet_name']} (还需{remaining}台 / 目标{outlet['target_quantity']}台)"
                self.plan_outlet_combo.addItem(display, outlet)

        batches = self.batch_service.get_all_batches()
        available_batches = [b for b in batches if b['remaining_quantity'] > 0]
        self.batch_combo = QComboBox()
        for b in available_batches:
            self.batch_combo.addItem(f"{b['batch_no']} (剩余{b['remaining_quantity']}台)", b['id'])

        self.quantity_spin = QSpinBox()
        self.quantity_spin.setRange(1, 10000)
        self.plan_outlet_combo.currentIndexChanged.connect(self.update_quantity_range)
        self.batch_combo.currentIndexChanged.connect(self.update_quantity_range)
        self.update_quantity_range()

        self.operator_edit = QLineEdit()
        self.remark_edit = QTextEdit()
        self.remark_edit.setMaximumHeight(60)

        layout.addRow("选择目标网点:", self.plan_outlet_combo)
        layout.addRow("选择批次:", self.batch_combo)
        layout.addRow("出库数量:", self.quantity_spin)
        layout.addRow("操作员:", self.operator_edit)
        layout.addRow("备注:", self.remark_edit)

        self.preview_label = QLabel("")
        self.preview_label.setStyleSheet("color: #2c7be5;")
        layout.addRow(self.preview_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.update_preview()
        self.quantity_spin.valueChanged.connect(self.update_preview)

    def update_quantity_range(self):
        current_outlet = self.plan_outlet_combo.currentData()
        current_batch_id = self.batch_combo.currentData()
        max_qty = 1
        if current_outlet:
            remaining = current_outlet['target_quantity'] - current_outlet['completed_quantity']
            max_qty = remaining
        if current_batch_id:
            batch = self.batch_service.get_batch_by_id(current_batch_id)
            if batch:
                max_qty = min(max_qty, batch['remaining_quantity'])
        self.quantity_spin.setMaximum(max(1, max_qty))

    def update_preview(self):
        outlet_data = self.plan_outlet_combo.currentData()
        outlet_name = outlet_data['outlet_name'] if outlet_data else "-"
        qty = self.quantity_spin.value()
        batch_text = self.batch_combo.currentText()
        self.preview_label.setText(f"预览: 从 {batch_text.split('(')[0]} 拆分 {qty} 台到 {outlet_name}")

    def validate_and_accept(self):
        if self.plan_outlet_combo.count() == 0:
            QMessageBox.warning(self, "警告", "没有待执行的网点任务")
            return
        if self.batch_combo.count() == 0:
            QMessageBox.warning(self, "警告", "没有可用批次")
            return
        self.accept()

    def get_data(self):
        outlet_data = self.plan_outlet_combo.currentData()
        return {
            'plan_id': self.plan['id'],
            'plan_outlet_id': outlet_data['id'],
            'batch_id': self.batch_combo.currentData(),
            'quantity': self.quantity_spin.value(),
            'operator': self.operator_edit.text().strip() or None,
            'remark': self.remark_edit.toPlainText().strip() or None
        }


class OutboundDialog(QDialog):
    def __init__(self, parent=None, batch_list=None, outlet_list=None):
        super().__init__(parent)
        self.setWindowTitle("拆分出库")
        self.setMinimumWidth(450)

        layout = QFormLayout(self)

        self.batch_combo = QComboBox()
        for batch in batch_list or []:
            display_text = f"{batch['batch_no']} (剩余: {batch['remaining_quantity']})"
            self.batch_combo.addItem(display_text, batch['id'])
        self.batch_combo.currentIndexChanged.connect(self.update_max_quantity)

        self.quantity_spin = QSpinBox()
        self.quantity_spin.setRange(1, 10000)

        self.outlet_combo = QComboBox()
        for outlet in outlet_list or []:
            display_text = f"{outlet['name']} ({outlet.get('location_type', '')})"
            self.outlet_combo.addItem(display_text, outlet['id'])

        self.operator_edit = QLineEdit()

        self.outbound_date_edit = QDateEdit()
        self.outbound_date_edit.setCalendarPopup(True)
        self.outbound_date_edit.setDate(QDate.currentDate())
        self.outbound_date_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")

        self.remark_edit = QTextEdit()
        self.remark_edit.setMaximumHeight(80)

        layout.addRow("选择批次:", self.batch_combo)
        layout.addRow("出库数量:", self.quantity_spin)
        layout.addRow("投放网点:", self.outlet_combo)
        layout.addRow("操作员:", self.operator_edit)
        layout.addRow("出库时间:", self.outbound_date_edit)
        layout.addRow("备注:", self.remark_edit)

        self.preview_label = QLabel("")
        self.preview_label.setStyleSheet("color: #666;")
        layout.addRow(self.preview_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.update_max_quantity()

    def update_max_quantity(self):
        if self.batch_combo.count() > 0:
            batch_id = self.batch_combo.currentData()
            batch_service = BatchService(self.parent().db if hasattr(self.parent(), 'db') else None)
            if batch_service.db:
                batch = batch_service.get_batch_by_id(batch_id)
                if batch:
                    self.quantity_spin.setMaximum(batch['remaining_quantity'])
                    self.update_preview()

    def update_preview(self):
        batch_text = self.batch_combo.currentText()
        quantity = self.quantity_spin.value()
        outlet_text = self.outlet_combo.currentText()
        self.preview_label.setText(f"预览: 从 {batch_text} 拆分 {quantity} 个到 {outlet_text}")

    def get_data(self):
        return {
            'batch_id': self.batch_combo.currentData(),
            'quantity': self.quantity_spin.value(),
            'outlet_id': self.outlet_combo.currentData(),
            'operator': self.operator_edit.text().strip() or None,
            'outbound_date': self.outbound_date_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
            'remark': self.remark_edit.toPlainText().strip() or None
        }


class OutboundTab(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.service = OutboundService(db)
        self.batch_service = BatchService(db)
        self.plan_service = DeploymentPlanService(db)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        button_layout = QHBoxLayout()
        self.add_btn = QPushButton("新建出库")
        self.add_btn.clicked.connect(self.add_outbound)
        self.view_detail_btn = QPushButton("查看详情")
        self.view_detail_btn.clicked.connect(self.view_detail)
        self.cancel_btn = QPushButton("撤销出库")
        self.cancel_btn.clicked.connect(self.cancel_outbound)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.load_data)

        button_layout.addWidget(self.add_btn)
        button_layout.addWidget(self.view_detail_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.refresh_btn)

        main_layout.addLayout(button_layout)

        self.tab_widget = QTabWidget()

        outbound_page = QWidget()
        outbound_layout = QVBoxLayout(outbound_page)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "ID", "出库单号", "批次号", "数量", "投放网点", "网点类型", "出库时间", "创建时间"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        outbound_layout.addWidget(self.table)

        distribution_page = QWidget()
        dist_layout = QVBoxLayout(distribution_page)

        dist_splitter = QSplitter(Qt.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("网点设备分布:"))
        self.outlet_table = QTableWidget()
        self.outlet_table.setColumnCount(7)
        self.outlet_table.setHorizontalHeaderLabels([
            "网点名称", "类型", "地址", "投放批次", "总设备", "可用", "故障"
        ])
        self.outlet_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.outlet_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.outlet_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.outlet_table.itemSelectionChanged.connect(self.load_outlet_devices)
        left_layout.addWidget(self.outlet_table)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("网点设备列表:"))
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(5)
        self.device_table.setHorizontalHeaderLabels([
            "设备编号", "批次号", "状态", "出库单号", "出库时间"
        ])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.device_table.setEditTriggers(QTableWidget.NoEditTriggers)
        right_layout.addWidget(self.device_table)

        dist_splitter.addWidget(left_widget)
        dist_splitter.addWidget(right_widget)
        dist_splitter.setSizes([500, 500])
        dist_layout.addWidget(dist_splitter)

        plan_page = QWidget()
        plan_layout = QVBoxLayout(plan_page)

        plan_button_layout = QHBoxLayout()
        self.add_plan_btn = QPushButton("📋 新建投放计划")
        self.add_plan_btn.clicked.connect(self.add_plan)
        self.execute_plan_btn = QPushButton("▶️ 执行计划")
        self.execute_plan_btn.clicked.connect(self.execute_plan)
        self.view_plan_btn = QPushButton("📊 查看计划")
        self.view_plan_btn.clicked.connect(self.view_plan)
        self.delete_plan_btn = QPushButton("🗑️ 删除计划")
        self.delete_plan_btn.clicked.connect(self.delete_plan)
        self.refresh_plan_btn = QPushButton("刷新")
        self.refresh_plan_btn.clicked.connect(self.load_plans)

        plan_button_layout.addWidget(self.add_plan_btn)
        plan_button_layout.addWidget(self.execute_plan_btn)
        plan_button_layout.addWidget(self.view_plan_btn)
        plan_button_layout.addWidget(self.delete_plan_btn)
        plan_button_layout.addStretch()
        plan_button_layout.addWidget(self.refresh_plan_btn)
        plan_layout.addLayout(plan_button_layout)

        self.plan_table = QTableWidget()
        self.plan_table.setColumnCount(10)
        self.plan_table.setHorizontalHeaderLabels([
            "ID", "计划号", "计划名称", "类型", "目标数量", "已完成",
            "完成率", "状态", "优先级", "计划日期"
        ])
        self.plan_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.plan_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.plan_table.setEditTriggers(QTableWidget.NoEditTriggers)
        plan_layout.addWidget(self.plan_table)

        self.tab_widget.addTab(outbound_page, "出库记录")
        self.tab_widget.addTab(distribution_page, "网点分布")
        self.tab_widget.addTab(plan_page, "📋 投放计划")

        main_layout.addWidget(self.tab_widget, 1)

        stats_group = QGroupBox("分布统计")
        stats_layout = QHBoxLayout(stats_group)
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(4)
        self.stats_table.setHorizontalHeaderLabels(["网点类型", "网点数", "设备数", "使用中"])
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stats_table.setMaximumHeight(150)
        stats_layout.addWidget(self.stats_table)
        main_layout.addWidget(stats_group)

    def load_data(self):
        outbounds = self.service.get_all_outbounds()
        self.table.setRowCount(len(outbounds))
        for row, ob in enumerate(outbounds):
            self.table.setItem(row, 0, QTableWidgetItem(str(ob['id'])))
            self.table.setItem(row, 1, QTableWidgetItem(ob['outbound_no']))
            self.table.setItem(row, 2, QTableWidgetItem(ob['batch_no']))
            qty_item = QTableWidgetItem(str(ob['quantity']))
            qty_item.setForeground(Qt.blue)
            self.table.setItem(row, 3, qty_item)
            self.table.setItem(row, 4, QTableWidgetItem(ob['outlet_name']))
            self.table.setItem(row, 5, QTableWidgetItem(ob.get('location_type') or '-'))
            self.table.setItem(row, 6, QTableWidgetItem(ob['outbound_date']))
            self.table.setItem(row, 7, QTableWidgetItem(ob['created_at']))

        outlets = self.service.get_outlet_distribution()
        self.outlet_table.setRowCount(len(outlets))
        for row, outlet in enumerate(outlets):
            self.outlet_table.setItem(row, 0, QTableWidgetItem(outlet['name']))
            self.outlet_table.setItem(row, 1, QTableWidgetItem(outlet.get('location_type') or '-'))
            self.outlet_table.setItem(row, 2, QTableWidgetItem(outlet.get('address') or '-'))
            self.outlet_table.setItem(row, 3, QTableWidgetItem(str(outlet['batch_count'])))
            self.outlet_table.setItem(row, 4, QTableWidgetItem(str(outlet['total_devices'])))
            available = outlet['deployed'] + outlet['in_use']
            avail_item = QTableWidgetItem(str(available))
            if available > 0:
                avail_item.setForeground(Qt.green)
            self.outlet_table.setItem(row, 5, avail_item)
            faulty_item = QTableWidgetItem(str(outlet['faulty']))
            if outlet['faulty'] > 0:
                faulty_item.setForeground(Qt.red)
            self.outlet_table.setItem(row, 6, faulty_item)

        stats = self.service.get_distribution_stats()
        self.stats_table.setRowCount(len(stats))
        for row, stat in enumerate(stats):
            self.stats_table.setItem(row, 0, QTableWidgetItem(stat.get('location_type') or '其他'))
            self.stats_table.setItem(row, 1, QTableWidgetItem(str(stat['outlet_count'])))
            self.stats_table.setItem(row, 2, QTableWidgetItem(str(stat['device_count'])))
            self.stats_table.setItem(row, 3, QTableWidgetItem(str(stat['in_use'])))

    def load_outlet_devices(self):
        current_row = self.outlet_table.currentRow()
        if current_row < 0:
            self.device_table.setRowCount(0)
            return

        outlet_name = self.outlet_table.item(current_row, 0).text()
        outlets = self.batch_service.get_all_outlets()
        outlet = next((o for o in outlets if o['name'] == outlet_name), None)

        if outlet:
            devices = self.service.get_outlet_devices(outlet['id'])
            self.device_table.setRowCount(len(devices))
            for row, device in enumerate(devices):
                self.device_table.setItem(row, 0, QTableWidgetItem(device['device_no']))
                self.device_table.setItem(row, 1, QTableWidgetItem(device['batch_no']))
                status_map = {
                    'deployed': ('已投放', Qt.green),
                    'in_use': ('使用中', Qt.darkYellow),
                    'faulty': ('故障', Qt.red)
                }
                status_text, status_color = status_map.get(device['status'], (device['status'], Qt.black))
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(status_color)
                self.device_table.setItem(row, 2, status_item)
                self.device_table.setItem(row, 3, QTableWidgetItem(device.get('outbound_no') or '-'))
                self.device_table.setItem(row, 4, QTableWidgetItem(device.get('outbound_date') or '-'))

    def add_outbound(self):
        batches = self.batch_service.get_all_batches()
        available_batches = [b for b in batches if b['remaining_quantity'] > 0]
        outlets = self.batch_service.get_all_outlets()

        if not available_batches:
            QMessageBox.warning(self, "警告", "没有可用的批次，请先创建设备批次")
            return

        if not outlets:
            QMessageBox.warning(self, "警告", "没有可用的网点，请先创建网点")
            return

        dialog = OutboundDialog(self, available_batches, outlets)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            if data['quantity'] <= 0:
                QMessageBox.warning(self, "警告", "出库数量必须大于0")
                return
            try:
                result = self.service.split_outbound(**data)
                self.load_data()
                QMessageBox.information(self, "成功",
                    f"出库成功!\n出库单号: {result['outbound_no']}\n设备数量: {data['quantity']}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"出库失败: {str(e)}")

    def view_detail(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要查看的出库记录")
            return

        outbound_id = int(self.table.item(current_row, 0).text())
        outbound = self.service.get_outbound_by_id(outbound_id)

        if outbound:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"出库详情 - {outbound['outbound_no']}")
            dialog.setMinimumSize(800, 600)
            layout = QVBoxLayout(dialog)

            info_layout = QHBoxLayout()
            info_layout.addWidget(QLabel(f"<b>批次号:</b> {outbound['batch_no']}"))
            info_layout.addWidget(QLabel(f"<b>数量:</b> {outbound['quantity']}"))
            info_layout.addWidget(QLabel(f"<b>网点:</b> {outbound['outlet_name']}"))
            info_layout.addWidget(QLabel(f"<b>时间:</b> {outbound['outbound_date']}"))
            info_layout.addStretch()
            layout.addLayout(info_layout)

            device_table = QTableWidget()
            device_table.setColumnCount(3)
            device_table.setHorizontalHeaderLabels(["设备编号", "状态", "最后归还"])
            device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            device_table.setEditTriggers(QTableWidget.NoEditTriggers)
            devices = outbound.get('devices', [])
            device_table.setRowCount(len(devices))
            for row, device in enumerate(devices):
                device_table.setItem(row, 0, QTableWidgetItem(device['device_no']))
                status_map = {
                    'deployed': ('已投放', Qt.green),
                    'in_use': ('使用中', Qt.darkYellow),
                    'faulty': ('故障', Qt.red)
                }
                status_text, status_color = status_map.get(device['status'], (device['status'], Qt.black))
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(status_color)
                device_table.setItem(row, 1, status_item)
                device_table.setItem(row, 2, QTableWidgetItem(device.get('last_return_time') or '-'))
            layout.addWidget(device_table)

            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            dialog.exec_()

    def cancel_outbound(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要撤销的出库记录")
            return

        outbound_id = int(self.table.item(current_row, 0).text())

        if QMessageBox.question(self, "确认",
                                 "确定要撤销该出库记录吗?\n注意: 存在故障或使用中设备时无法撤销",
                                 QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                self.service.cancel_outbound(outbound_id)
                self.load_data()
                QMessageBox.information(self, "成功", "出库已撤销")
            except ValueError as e:
                QMessageBox.warning(self, "警告", str(e))
            except Exception as e:
                QMessageBox.critical(self, "错误", f"撤销失败: {str(e)}")

    def load_plans(self):
        plans = self.plan_service.get_all_plans()
        self.plan_table.setRowCount(len(plans))
        status_map = {
            'pending': ('待执行', Qt.blue),
            'in_progress': ('进行中', Qt.darkYellow),
            'completed': ('已完成', Qt.green)
        }
        priority_map = {
            'normal': '一般',
            'high': '优先',
            'urgent': '紧急'
        }
        for row, plan in enumerate(plans):
            self.plan_table.setItem(row, 0, QTableWidgetItem(str(plan['id'])))
            self.plan_table.setItem(row, 1, QTableWidgetItem(plan['plan_no']))
            self.plan_table.setItem(row, 2, QTableWidgetItem(plan['plan_name']))
            self.plan_table.setItem(row, 3, QTableWidgetItem(plan['location_type']))
            self.plan_table.setItem(row, 4, QTableWidgetItem(str(plan['target_quantity'])))
            self.plan_table.setItem(row, 5, QTableWidgetItem(str(plan['completed_quantity'])))

            progress = 0 if plan['target_quantity'] == 0 else (plan['completed_quantity'] / plan['target_quantity'] * 100)
            progress_item = QTableWidgetItem(f"{progress:.1f}%")
            if progress >= 100:
                progress_item.setForeground(Qt.green)
            elif progress >= 50:
                progress_item.setForeground(Qt.darkYellow)
            else:
                progress_item.setForeground(Qt.red)
            self.plan_table.setItem(row, 6, progress_item)

            status_text, status_color = status_map.get(plan['status'], (plan['status'], Qt.black))
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(status_color)
            self.plan_table.setItem(row, 7, status_item)

            priority_text = priority_map.get(plan.get('priority', ''), plan.get('priority', ''))
            self.plan_table.setItem(row, 8, QTableWidgetItem(priority_text))
            self.plan_table.setItem(row, 9, QTableWidgetItem(plan['plan_date']))

    def add_plan(self):
        outlets = self.batch_service.get_all_outlets()
        outlets_by_type = {}
        for o in outlets:
            lt = o.get('location_type') or '其他'
            if lt not in outlets_by_type:
                outlets_by_type[lt] = []
            outlets_by_type[lt].append(o)

        dialog = PlanDialog(self, outlets_by_type)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            try:
                plan_id = self.plan_service.create_plan(**data)
                self.load_plans()
                QMessageBox.information(self, "成功", f"投放计划创建成功!\n计划ID: {plan_id}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"创建失败: {str(e)}")

    def execute_plan(self):
        current_row = self.plan_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要执行的计划")
            return
        plan_id = int(self.plan_table.item(current_row, 0).text())
        plan = self.plan_service.get_plan_by_id(plan_id)
        if not plan:
            QMessageBox.warning(self, "警告", "计划不存在")
            return
        if plan['status'] == 'completed':
            QMessageBox.information(self, "提示", "该计划已全部完成")
            return

        dialog = PlanExecutionDialog(self, plan, self.plan_service, self.batch_service)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            try:
                result = self.plan_service.execute_plan_outlet(**data)
                self.load_data()
                self.load_plans()
                QMessageBox.information(self, "成功",
                    f"出库成功!\n"
                    f"出库单号: {result['outbound_no']}\n"
                    f"设备数量: {data['quantity']}")
            except ValueError as e:
                QMessageBox.warning(self, "警告", str(e))
            except Exception as e:
                QMessageBox.critical(self, "错误", f"执行失败: {str(e)}")

    def view_plan(self):
        current_row = self.plan_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要查看的计划")
            return
        plan_id = int(self.plan_table.item(current_row, 0).text())
        plan = self.plan_service.get_plan_by_id(plan_id)
        if plan:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"计划详情 - {plan['plan_name']}")
            dialog.setMinimumSize(950, 700)
            layout = QVBoxLayout(dialog)

            info_group = QGroupBox("计划信息")
            info_layout = QHBoxLayout(info_group)
            info_layout.addWidget(QLabel(f"<b>计划号:</b> {plan['plan_no']}"))
            info_layout.addWidget(QLabel(f"<b>类型:</b> {plan['location_type']}"))
            progress = 0 if plan['target_quantity'] == 0 else (plan['completed_quantity'] / plan['target_quantity'] * 100)
            info_layout.addWidget(QLabel(f"<b>进度:</b> {plan['completed_quantity']}/{plan['target_quantity']} ({progress:.1f}%)"))
            status_map = {'pending': '待执行', 'in_progress': '进行中', 'completed': '已完成'}
            info_layout.addWidget(QLabel(f"<b>状态:</b> {status_map.get(plan['status'], plan['status'])}"))
            info_layout.addStretch()
            layout.addWidget(info_group)

            progress_bar = QProgressBar()
            progress_bar.setValue(int(progress))
            progress_bar.setFormat(f"{progress:.1f}%")
            progress_bar.setStyleSheet("QProgressBar { height: 25px; text-align: center; }")
            layout.addWidget(progress_bar)

            content_tabs = QTabWidget()

            outlet_tab = QWidget()
            outlet_layout = QVBoxLayout(outlet_tab)
            outlet_layout.addWidget(QLabel("各网点完成情况:"))
            outlet_table = QTableWidget()
            outlet_table.setColumnCount(6)
            outlet_table.setHorizontalHeaderLabels(["网点名称", "类型", "目标", "已完成", "剩余", "完成率"])
            outlet_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            outlets = plan.get('outlets', [])
            outlet_table.setRowCount(len(outlets))
            for r, o in enumerate(outlets):
                outlet_table.setItem(r, 0, QTableWidgetItem(o['outlet_name']))
                outlet_table.setItem(r, 1, QTableWidgetItem(o.get('outlet_location_type', '-')))
                outlet_table.setItem(r, 2, QTableWidgetItem(str(o['target_quantity'])))
                outlet_table.setItem(r, 3, QTableWidgetItem(str(o['completed_quantity'])))
                remaining = o['target_quantity'] - o['completed_quantity']
                remaining_item = QTableWidgetItem(str(remaining))
                if remaining > 0:
                    remaining_item.setForeground(Qt.red)
                outlet_table.setItem(r, 4, remaining_item)
                outlet_p = 0 if o['target_quantity'] == 0 else (o['completed_quantity'] / o['target_quantity'] * 100)
                outlet_table.setItem(r, 5, QTableWidgetItem(f"{outlet_p:.1f}%"))
            outlet_layout.addWidget(outlet_table)

            exec_tab = QWidget()
            exec_layout = QVBoxLayout(exec_tab)
            exec_layout.addWidget(QLabel("执行记录:"))
            exec_table = QTableWidget()
            exec_table.setColumnCount(5)
            exec_table.setHorizontalHeaderLabels(["出库单号", "批次号", "网点", "数量", "出库时间"])
            exec_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            executions = plan.get('executions', [])
            exec_table.setRowCount(len(executions))
            for r, e in enumerate(executions):
                exec_table.setItem(r, 0, QTableWidgetItem(e['outbound_no']))
                exec_table.setItem(r, 1, QTableWidgetItem(e['batch_no']))
                exec_table.setItem(r, 2, QTableWidgetItem(e['outlet_name']))
                exec_table.setItem(r, 3, QTableWidgetItem(str(e['quantity'])))
                exec_table.setItem(r, 4, QTableWidgetItem(e['outbound_date']))
            exec_layout.addWidget(exec_table)

            content_tabs.addTab(outlet_tab, "网点目标")
            content_tabs.addTab(exec_tab, "执行记录")
            layout.addWidget(content_tabs, 1)

            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            dialog.exec_()

    def delete_plan(self):
        current_row = self.plan_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要删除的计划")
            return
        plan_id = int(self.plan_table.item(current_row, 0).text())
        if QMessageBox.question(self, "确认", "确定要删除该计划吗?\n已有出库记录的计划无法删除",
                                  QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                self.plan_service.delete_plan(plan_id)
                self.load_plans()
                QMessageBox.information(self, "成功", "计划删除成功")
            except ValueError as e:
                QMessageBox.warning(self, "警告", str(e))
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败: {str(e)}")
