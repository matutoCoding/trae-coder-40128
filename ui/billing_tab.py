from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                             QPushButton, QDialog, QFormLayout, QLineEdit, QDoubleSpinBox,
                             QSpinBox, QMessageBox, QHeaderView, QLabel, QGroupBox, QDialogButtonBox)
from PyQt5.QtCore import Qt
from services.billing_service import BillingService


class RuleDialog(QDialog):
    def __init__(self, parent=None, rule=None):
        super().__init__(parent)
        self.setWindowTitle("计费规则" if rule else "新增计费规则")
        self.setMinimumWidth(400)
        self.rule = rule

        layout = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.start_price_spin = QDoubleSpinBox()
        self.start_price_spin.setRange(0, 1000)
        self.start_price_spin.setDecimals(2)
        self.start_price_spin.setSuffix(" 元")

        self.free_minutes_spin = QSpinBox()
        self.free_minutes_spin.setRange(0, 120)
        self.free_minutes_spin.setSuffix(" 分钟")

        self.price_per_hour_spin = QDoubleSpinBox()
        self.price_per_hour_spin.setRange(0, 1000)
        self.price_per_hour_spin.setDecimals(2)
        self.price_per_hour_spin.setSuffix(" 元/小时")

        self.max_price_per_day_spin = QDoubleSpinBox()
        self.max_price_per_day_spin.setRange(0, 10000)
        self.max_price_per_day_spin.setDecimals(2)
        self.max_price_per_day_spin.setSuffix(" 元/天")

        layout.addRow("规则名称:", self.name_edit)
        layout.addRow("起步价:", self.start_price_spin)
        layout.addRow("免费时长:", self.free_minutes_spin)
        layout.addRow("每小时单价:", self.price_per_hour_spin)
        layout.addRow("每日封顶价:", self.max_price_per_day_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        if rule:
            self.name_edit.setText(rule['name'])
            self.start_price_spin.setValue(rule['start_price'])
            self.free_minutes_spin.setValue(rule['free_minutes'])
            self.price_per_hour_spin.setValue(rule['price_per_hour'])
            self.max_price_per_day_spin.setValue(rule['max_price_per_day'])

    def get_data(self):
        return {
            'name': self.name_edit.text().strip(),
            'start_price': self.start_price_spin.value(),
            'free_minutes': self.free_minutes_spin.value(),
            'price_per_hour': self.price_per_hour_spin.value(),
            'max_price_per_day': self.max_price_per_day_spin.value()
        }


class BillingTab(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.service = BillingService(db)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        button_layout = QHBoxLayout()
        self.add_btn = QPushButton("新增规则")
        self.add_btn.clicked.connect(self.add_rule)
        self.edit_btn = QPushButton("编辑规则")
        self.edit_btn.clicked.connect(self.edit_rule)
        self.set_active_btn = QPushButton("设为当前规则")
        self.set_active_btn.clicked.connect(self.set_active_rule)
        self.delete_btn = QPushButton("删除规则")
        self.delete_btn.clicked.connect(self.delete_rule)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.load_data)

        button_layout.addWidget(self.add_btn)
        button_layout.addWidget(self.edit_btn)
        button_layout.addWidget(self.set_active_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.refresh_btn)

        main_layout.addLayout(button_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["ID", "规则名称", "起步价", "免费时长", "每小时单价", "每日封顶价", "状态", "创建时间"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        main_layout.addWidget(self.table)

        calc_group = QGroupBox("费用试算")
        calc_layout = QHBoxLayout(calc_group)

        calc_layout.addWidget(QLabel("租借时长(小时):"))
        self.hours_spin = QDoubleSpinBox()
        self.hours_spin.setRange(0.1, 720)
        self.hours_spin.setDecimals(1)
        self.hours_spin.setValue(2)
        calc_layout.addWidget(self.hours_spin)

        self.calc_btn = QPushButton("计算费用")
        self.calc_btn.clicked.connect(self.calculate_fee)
        calc_layout.addWidget(self.calc_btn)

        self.result_label = QLabel("")
        self.result_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c7be5;")
        calc_layout.addWidget(self.result_label)
        calc_layout.addStretch()

        main_layout.addWidget(calc_group)

        self.breakdown_table = QTableWidget()
        self.breakdown_table.setColumnCount(2)
        self.breakdown_table.setHorizontalHeaderLabels(["计费步骤", "金额(元)"])
        self.breakdown_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.breakdown_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.breakdown_table.setMaximumHeight(200)
        main_layout.addWidget(self.breakdown_table)

    def load_data(self):
        rules = self.service.get_all_rules()
        self.table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            self.table.setItem(row, 0, QTableWidgetItem(str(rule['id'])))
            self.table.setItem(row, 1, QTableWidgetItem(rule['name']))
            self.table.setItem(row, 2, QTableWidgetItem(f"{rule['start_price']:.2f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{rule['free_minutes']}分钟"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{rule['price_per_hour']:.2f}"))
            self.table.setItem(row, 5, QTableWidgetItem(f"{rule['max_price_per_day']:.2f}"))
            status_item = QTableWidgetItem("当前使用" if rule['is_active'] else "未启用")
            if rule['is_active']:
                status_item.setForeground(Qt.green)
            self.table.setItem(row, 6, status_item)
            self.table.setItem(row, 7, QTableWidgetItem(rule['created_at']))

    def add_rule(self):
        dialog = RuleDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            if not data['name']:
                QMessageBox.warning(self, "警告", "请输入规则名称")
                return
            try:
                self.service.add_rule(**data)
                self.load_data()
                QMessageBox.information(self, "成功", "计费规则添加成功")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"添加失败: {str(e)}")

    def edit_rule(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要编辑的规则")
            return

        rule_id = int(self.table.item(current_row, 0).text())
        rule = self.service.get_all_rules()
        rule = next((r for r in rule if r['id'] == rule_id), None)

        if rule:
            dialog = RuleDialog(self, rule)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.get_data()
                if not data['name']:
                    QMessageBox.warning(self, "警告", "请输入规则名称")
                    return
                try:
                    self.service.update_rule(rule_id, **data)
                    self.load_data()
                    QMessageBox.information(self, "成功", "计费规则更新成功")
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"更新失败: {str(e)}")

    def set_active_rule(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要启用的规则")
            return

        rule_id = int(self.table.item(current_row, 0).text())
        try:
            self.service.set_active_rule(rule_id)
            self.load_data()
            QMessageBox.information(self, "成功", "已设为当前计费规则")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"设置失败: {str(e)}")

    def delete_rule(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请选择要删除的规则")
            return

        rule_id = int(self.table.item(current_row, 0).text())
        status = self.table.item(current_row, 6).text()
        if status == "当前使用":
            QMessageBox.warning(self, "警告", "当前使用的规则无法删除")
            return

        if QMessageBox.question(self, "确认", "确定要删除该规则吗?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                self.service.delete_rule(rule_id)
                self.load_data()
                QMessageBox.information(self, "成功", "规则删除成功")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败: {str(e)}")

    def calculate_fee(self):
        hours = self.hours_spin.value()
        try:
            result = self.service.simulate_fee(hours)
            duration_minutes = int(hours * 60)
            breakdown = self.service.get_fee_breakdown(duration_minutes)

            self.result_label.setText(
                f"时长: {result['duration_minutes']}分钟 | "
                f"计费: {result['billable_minutes']}分钟 | "
                f"计算金额: {result['calculated_amount']:.2f}元 | "
                f"实付: <span style='color: #e74c3c;'>{result['final_amount']:.2f}</span>元"
            )
            self.result_label.setTextFormat(Qt.RichText)

            if breakdown:
                self.breakdown_table.setRowCount(len(breakdown['steps']) + 2)
                for i, step in enumerate(breakdown['steps']):
                    self.breakdown_table.setItem(i, 0, QTableWidgetItem(step['description']))
                    amount_item = QTableWidgetItem(f"{step['amount']:.2f}")
                    if step['amount'] < 0:
                        amount_item.setForeground(Qt.green)
                    self.breakdown_table.setItem(i, 1, amount_item)

                total_row = len(breakdown['steps'])
                self.breakdown_table.setItem(total_row, 0, QTableWidgetItem("计算总价"))
                self.breakdown_table.setItem(total_row, 1, QTableWidgetItem(f"{breakdown.get('total', 0):.2f}"))

                final_row = total_row + 1
                final_item = QTableWidgetItem("最终应收")
                final_item.setForeground(Qt.red)
                self.breakdown_table.setItem(final_row, 0, final_item)
                final_amount = QTableWidgetItem(f"{breakdown.get('final', 0):.2f}")
                final_amount.setForeground(Qt.red)
                self.breakdown_table.setItem(final_row, 1, final_amount)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"计算失败: {str(e)}")
