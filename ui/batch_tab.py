from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                             QPushButton, QDialog, QFormLayout, QLineEdit, QDoubleSpinBox,
                             QSpinBox, QMessageBox, QHeaderView, QLabel, QGroupBox,
                             QDialogButtonBox, QDateEdit, QTextEdit, QSplitter, QComboBox)
from PyQt5.QtCore import Qt, QDate
from services.batch_service import BatchService


class BatchDialog(QDialog):
    def __init__(self, parent=None, batch=None):
        super().__init__(parent)
        self.setWindowTitle("编辑批次" if batch else "新增批次")
        self.setMinimumWidth(450)
        self.batch = batch

        layout = QFormLayout(self)

        self.quantity_spin = QSpinBox()
        self.quantity_spin.setRange(1, 10000)
        self.quantity_spin.setValue(100)

        self.model_edit = QLineEdit()
        self.purchase_date_edit = QDateEdit()
        self.purchase_date_edit.setCalendarPopup(True)
        self.purchase_date_edit.setDate(QDate.currentDate())
        self.purchase_date_edit.setDisplayFormat("yyyy-MM-dd")

        self.supplier_edit = QLineEdit()
        self.unit_cost_spin = QDoubleSpinBox()
        self.unit_cost_spin.setRange(0, 10000)
        self.unit_cost_spin.setDecimals(2)
        self.unit_cost_spin.setSuffix(" 元")

        self.remark_edit = QTextEdit()
        self.remark_edit.setMaximumHeight(80)

        if batch:
            layout.addRow("批次号:", QLabel(batch['batch_no']))
            layout.addRow("总数:", QLabel(str(batch['total_quantity'])))
        else:
            layout.addRow("设备数量:", self.quantity_spin)

        layout.addRow("设备型号:", self.model_edit)
        layout.addRow("采购日期:", self.purchase_date_edit)
        layout.addRow("供应商:", self.supplier_edit)
        layout.addRow("单位成本:", self.unit_cost_spin)
        layout.addRow("备注:", self.remark_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        if batch:
            self.model_edit.setText(batch.get('model', '') or '')
            if batch.get('purchase_date'):
                self.purchase_date_edit.setDate(QDate.fromString(batch['purchase_date'], "yyyy-MM-dd"))
            self.supplier_edit.setText(batch.get('supplier', '') or '')
            if batch.get('unit_cost'):
                self.unit_cost_spin.setValue(float(batch['unit_cost']))
            self.remark_edit.setPlainText(batch.get('remark', '') or '')

    def get_data(self):
        return {
            'total_quantity': self.quantity_spin.value() if not self.batch else None,
            'model': self.model_edit.text().strip() or None,
            'purchase_date': self.purchase_date_edit.date().toString("yyyy-MM-dd"),
            'supplier': self.supplier_edit.text().strip() or None,
            'unit_cost': self.unit_cost_spin.value() or None,
            'remark': self.remark_edit.toPlainText().strip() or None
        }


class BatchTab(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.service = BatchService(db)
        self.init_ui()
        self.load_data()
        self.load_summary()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        summary_group = QGroupBox("库存概览")
        summary_layout = QHBoxLayout(summary_group)
        self.summary_labels = {}
        summary_items = [
            ('total_batches', '总批次'),
            ('total_devices', '总设备'),
            ('in_stock', '库存中'),
            ('deployed', '已投放'),
            ('in_use', '使用中'),
            ('faulty', '故障'),
            ('active_outlets', '活跃网点')
        ]
        for key, label in summary_items:
            item_layout = QVBoxLayout()
            self.summary_labels[key] = QLabel("0")
            self.summary_labels[key].setStyleSheet("font-size: 18px; font-weight: bold; color: #2c7be5;")
            item_layout.addWidget(self.summary_labels[key])
            item_layout.addWidget(QLabel(label))
            summary_layout.addLayout(item_layout)
        main_layout.addWidget(summary_group)

        button_layout = QHBoxLayout()
        self.add_btn = QPushButton("新增批次")
        self.add_btn.clicked.connect(self.add_batch)
        self.edit_btn = QPushButton("编辑批次")
        self.edit_btn.clicked.connect(self.edit_batch)
        self.view_detail_btn = QPushButton("查看详情")
        self.view_detail_btn.clicked.connect(self.view_detail)
        self.delete_btn = QPushButton("删除批次")
        self.delete_btn.clicked.connect(self.delete_batch)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.load_data)

        button_layout.addWidget(self.add_btn)
        button_layout.addWidget(self.edit_btn)
        button_layout.addWidget(self.view_detail_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.refresh_btn)

        main_layout.addLayout(button_layout)

        splitter = QSplitter(Qt.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "ID", "批次号", "总数", "已出库", "剩余", "型号", "采购日期", "创建时间"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.load_distribution)
        left_layout.addWidget(self.table)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addWidget(QLabel("网点分布情况:"))
        self.distribution_table = QTableWidget()
        self.distribution_table.setColumnCount(5)
        self.distribution_table.setHorizontalHeaderLabels([
            "网点名称", "类型", "投放数量", "可用", "故障"
        ])
        self.distribution_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.distribution_table.setEditTriggers(QTableWidget.NoEditTriggers)
        right_layout.addWidget(self.distribution_table)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([600, 400])

        main_layout.addWidget(splitter, 1)

    def load_summary(self):
        summary = self.service.get_distribution_summary()
        for key, label in self.summary_labels.items():
            value = summary.get(key, 0) or 0
            label.setText(str(value))

    def load_data(self):
        batches = self.service.get_all_batches()
        self.table.setRowCount(len(batches))
        for row, batch in enumerate(batches):
            self.table.setItem(row, 0, QTableWidgetItem(str(batch['id'])))
            self.table.setItem(row, 1, QTableWidgetItem(batch['batch_no']))
            self.table.setItem(row, 2, QTableWidgetItem(str(batch['total_quantity'])))
            deployed = batch['total_quantity'] - batch['remaining_quantity']
            self.table.setItem(row, 3, QTableWidgetItem(str(deployed)))
            rem_item = QTableWidgetItem(str(batch['remaining_quantity']))
            if batch['remaining_quantity'] > 0:
                rem_item.setForeground(Qt.green)
            self.table.setItem(row, 4, rem_item)
            self.table.setItem(row, 5, QTableWidgetItem(batch.get('model') or '-'))
            self.table.setItem(row, 6, QTableWidgetItem(batch.get('purchase_date') or '-'))
            self.table.setItem(row, 7, QTableWidgetItem(batch['created_at']))

        self.load_summary()

    def load_distribution(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            self.distribution_table.setRowCount(0)
            return

        batch_id = int(self.table.item(current_row, 0).text())
        distribution = self.service.get_batch_distribution(batch_id)

        self.distribution_table.setRowCount(len(distribution))
        for row, item in enumerate(distribution):
            self.distribution_table.setItem(row, 0, QTableWidgetItem(item['name']))
            self.distribution_table.setItem(row, 1, QTableWidgetItem(item.get('location_type') or '-'))
            self.distribution_table.setItem(row, 2, QTableWidgetItem(str(item['device_count'])))
            available = item['deployed_count'] + item['in_use_count']
            self.distribution_table.setItem(row, 3, QTableWidgetItem(str(available)))
            faulty_item = QTableWidgetItem(str(item['faulty_count']))
            if item['faulty_count'] > 0:
                faulty_item.setForeground(Qt.red)
            self.distribution_table.setItem(row, 4, faulty_item)

    def add_batch(self):
        dialog = BatchDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            if data['total_quantity'] <= 0:
                QMessageBox.warning(self, "警告", "设备数量必须大于0")
                return
            try:
                self.service.add_batch(
                    total_quantity=data['total_quantity'],
                    model=data['model'],
                    purchase_date=data['purchase_date'],
                    supplier=data['supplier'],
                    unit_cost=data['unit_cost'],
                    remark=data['remark']
                )
                self.load_data()
                QMessageBox.information(self, "成功", "批次添加成功")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"添加失败: {str(e)}")

    def edit_batch(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要编辑的批次")
            return

        batch_id = int(self.table.item(current_row, 0).text())
        batch = self.service.get_batch_by_id(batch_id)

        if batch:
            dialog = BatchDialog(self, batch)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.get_data()
                try:
                    self.service.update_batch(
                        batch_id,
                        model=data['model'],
                        purchase_date=data['purchase_date'],
                        supplier=data['supplier'],
                        unit_cost=data['unit_cost'],
                        remark=data['remark']
                    )
                    self.load_data()
                    QMessageBox.information(self, "成功", "批次更新成功")
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"更新失败: {str(e)}")

    def view_detail(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要查看的批次")
            return

        batch_id = int(self.table.item(current_row, 0).text())
        batch = self.service.get_batch_by_id(batch_id)

        if batch:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"批次详情 - {batch['batch_no']}")
            dialog.setMinimumSize(800, 600)
            layout = QVBoxLayout(dialog)

            info_layout = QHBoxLayout()
            info_layout.addWidget(QLabel(f"<b>批次号:</b> {batch['batch_no']}"))
            info_layout.addWidget(QLabel(f"<b>总数:</b> {batch['total_quantity']}"))
            info_layout.addWidget(QLabel(f"<b>剩余:</b> {batch['remaining_quantity']}"))
            info_layout.addWidget(QLabel(f"<b>型号:</b> {batch.get('model') or '-'}"))
            info_layout.addStretch()
            layout.addLayout(info_layout)

            device_table = QTableWidget()
            device_table.setColumnCount(5)
            device_table.setHorizontalHeaderLabels(["设备编号", "状态", "所在网点", "最后借出", "最后归还"])
            device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            device_table.setEditTriggers(QTableWidget.NoEditTriggers)
            devices = batch.get('devices', [])
            device_table.setRowCount(len(devices))
            for row, device in enumerate(devices):
                device_table.setItem(row, 0, QTableWidgetItem(device['device_no']))
                status_map = {
                    'in_stock': ('库存中', Qt.blue),
                    'deployed': ('已投放', Qt.green),
                    'in_use': ('使用中', Qt.darkYellow),
                    'faulty': ('故障', Qt.red)
                }
                status_text, status_color = status_map.get(device['status'], (device['status'], Qt.black))
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(status_color)
                device_table.setItem(row, 1, status_item)
                device_table.setItem(row, 2, QTableWidgetItem(device.get('outlet_name') or '-'))
                device_table.setItem(row, 3, QTableWidgetItem(device.get('last_borrow_time') or '-'))
                device_table.setItem(row, 4, QTableWidgetItem(device.get('last_return_time') or '-'))
            layout.addWidget(device_table)

            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            dialog.exec_()

    def delete_batch(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要删除的批次")
            return

        batch_id = int(self.table.item(current_row, 0).text())

        if QMessageBox.question(self, "确认", "确定要删除该批次吗?\n注意: 已出库的批次无法删除",
                                 QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                self.service.delete_batch(batch_id)
                self.load_data()
                QMessageBox.information(self, "成功", "批次删除成功")
            except ValueError as e:
                QMessageBox.warning(self, "警告", str(e))
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败: {str(e)}")
