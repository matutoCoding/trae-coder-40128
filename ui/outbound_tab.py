from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                             QPushButton, QDialog, QFormLayout, QLineEdit, QSpinBox,
                             QMessageBox, QHeaderView, QLabel, QGroupBox,
                             QDialogButtonBox, QDateEdit, QTextEdit, QSplitter, QComboBox,
                             QTabWidget)
from PyQt5.QtCore import Qt, QDate
from services.outbound_service import OutboundService
from services.batch_service import BatchService


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

        self.tab_widget.addTab(outbound_page, "出库记录")
        self.tab_widget.addTab(distribution_page, "网点分布")

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
