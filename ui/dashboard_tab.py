from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                             QPushButton, QDialog, QFormLayout, QLineEdit, QSpinBox,
                             QMessageBox, QHeaderView, QLabel, QGroupBox,
                             QDialogButtonBox, QDateEdit, QComboBox, QFrame,
                             QGridLayout, QSplitter, QCheckBox, QTabWidget)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QFont
from services.dashboard_service import DashboardService
from services.suggestion_service import SuggestionService
from services.deployment_plan_service import DeploymentPlanService
from services.batch_service import BatchService
from ui.outbound_tab import PlanDialog


class OutletDetailDialog(QDialog):
    def __init__(self, parent=None, outlet_id=None, outlet_name=None,
                 dashboard_service=None, start_date=None, end_date=None):
        super().__init__(parent)
        self.setWindowTitle(f"网点明细 - {outlet_name}")
        self.setMinimumSize(1050, 700)
        self.outlet_id = outlet_id
        self.outlet_name = outlet_name
        self.dashboard_service = dashboard_service
        self.start_date = start_date
        self.end_date = end_date

        layout = QVBoxLayout(self)

        info_label = QLabel(f"<h3>{outlet_name}</h3>日期区间: {start_date or '全部'} ~ {end_date or '全部'}")
        layout.addWidget(info_label)

        tabs = QTabWidget()

        device_tab = QWidget()
        device_layout = QVBoxLayout(device_tab)
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(6)
        self.device_table.setHorizontalHeaderLabels([
            "设备编号", "批次号", "状态", "出库单号", "出库时间", "最后归还"
        ])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.device_table.setEditTriggers(QTableWidget.NoEditTriggers)
        device_layout.addWidget(self.device_table)
        tabs.addTab(device_tab, "📦 设备明细")

        order_tab = QWidget()
        order_layout = QVBoxLayout(order_tab)
        self.order_table = QTableWidget()
        self.order_table.setColumnCount(8)
        self.order_table.setHorizontalHeaderLabels([
            "订单号", "设备编号", "借出时间", "归还时间", "时长(分)",
            "计费金额", "实收金额", "状态"
        ])
        self.order_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.order_table.setEditTriggers(QTableWidget.NoEditTriggers)
        order_layout.addWidget(self.order_table)
        tabs.addTab(order_tab, "📒 订单明细")

        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.load_data()

    def load_data(self):
        devices = self.dashboard_service.get_outlet_devices_detail(self.outlet_id)
        self.device_table.setRowCount(len(devices))
        status_map = {
            'in_stock': ('在库', Qt.gray),
            'deployed': ('已投放', Qt.green),
            'in_use': ('使用中', Qt.darkYellow),
            'faulty': ('故障', Qt.red)
        }
        for row, d in enumerate(devices):
            self.device_table.setItem(row, 0, QTableWidgetItem(d.get('device_no', '')))
            self.device_table.setItem(row, 1, QTableWidgetItem(d.get('batch_no', '')))
            st, sc = status_map.get(d.get('status', ''), (d.get('status', ''), Qt.black))
            si = QTableWidgetItem(st)
            si.setForeground(sc)
            self.device_table.setItem(row, 2, si)
            self.device_table.setItem(row, 3, QTableWidgetItem(d.get('outbound_no') or '-'))
            self.device_table.setItem(row, 4, QTableWidgetItem(d.get('outbound_date') or '-'))
            self.device_table.setItem(row, 5, QTableWidgetItem(d.get('last_return_time') or '-'))

        orders = self.dashboard_service.get_outlet_orders_detail(
            self.outlet_id, self.start_date, self.end_date
        )
        self.order_table.setRowCount(len(orders))
        for row, o in enumerate(orders):
            self.order_table.setItem(row, 0, QTableWidgetItem(o.get('order_no', '')))
            self.order_table.setItem(row, 1, QTableWidgetItem(o.get('device_no', '')))
            self.order_table.setItem(row, 2, QTableWidgetItem(o.get('borrow_time', '')))
            self.order_table.setItem(row, 3, QTableWidgetItem(o.get('return_time') or '进行中'))
            self.order_table.setItem(row, 4, QTableWidgetItem(str(o.get('duration_minutes') or '-')))
            calc_amount = o.get('calculated_amount') or o.get('final_amount') or 0
            self.order_table.setItem(row, 5, QTableWidgetItem(f"{calc_amount:.2f}"))
            self.order_table.setItem(row, 6, QTableWidgetItem(f"{o.get('final_amount', 0):.2f}"))
            status = '进行中' if o.get('status') == 'active' else '已完成'
            self.order_table.setItem(row, 7, QTableWidgetItem(status))


class DashboardTab(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.service = DashboardService(db)
        self.suggestion_service = SuggestionService(db)
        self.plan_service = DeploymentPlanService(db)
        self.batch_service = BatchService(db)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        filter_group = QGroupBox("筛选条件")
        filter_layout = QHBoxLayout(filter_group)

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

        filter_layout.addWidget(QLabel("网点类型:"))
        self.location_type_combo = QComboBox()
        self.location_type_combo.addItem("全部", None)
        filter_layout.addWidget(self.location_type_combo)

        filter_layout.addWidget(QLabel("网点:"))
        self.outlet_combo = QComboBox()
        self.outlet_combo.addItem("全部", None)
        filter_layout.addWidget(self.outlet_combo)

        self.filter_btn = QPushButton("🔍 查询")
        self.filter_btn.clicked.connect(self.load_data)
        filter_layout.addWidget(self.filter_btn)

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.load_data)
        filter_layout.addWidget(self.refresh_btn)

        filter_layout.addStretch()
        main_layout.addWidget(filter_group)

        self.content_tabs = QTabWidget()

        dashboard_page = QWidget()
        dashboard_layout = QVBoxLayout(dashboard_page)

        stats_group = QGroupBox("核心指标")
        stats_layout = QGridLayout(stats_group)
        self.stat_labels = {}
        stat_defs = [
            ('total_devices', '📦 设备总量', '#2c7be5'),
            ('in_stock', '🏠 在库', '#95a5a6'),
            ('deployed_in_use', '📍 已投放(含使用)', '#27ae60'),
            ('in_use', '🔋 使用中', '#f39c12'),
            ('faulty', '⚠️ 故障', '#e74c3c'),
            ('total_orders', '📋 订单数', '#8e44ad'),
            ('active_orders', '⏳ 进行中订单', '#d35400'),
            ('total_revenue', '💰 营收(元)', '#16a085'),
            ('avg_amount', '💵 平均客单(元)', '#2980b9'),
            ('avg_duration', '⏱️ 平均时长(分)', '#c0392b'),
        ]
        for idx, (key, name, color) in enumerate(stat_defs):
            r, c = divmod(idx, 5)
            card = QFrame()
            card.setStyleSheet(f"QFrame {{ border: 1px solid #ddd; border-radius: 8px; background: white; }}")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 10, 15, 10)
            title_lbl = QLabel(name)
            title_lbl.setStyleSheet("color: #666; font-size: 12px;")
            value_lbl = QLabel("-")
            value_lbl.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: bold;")
            self.stat_labels[key] = value_lbl
            card_layout.addWidget(title_lbl)
            card_layout.addWidget(value_lbl)
            stats_layout.addWidget(card, r, c)
        dashboard_layout.addWidget(stats_group)

        outlet_group = QGroupBox("网点运营明细 (双击查看设备/订单)")
        outlet_layout = QVBoxLayout(outlet_group)
        self.outlet_table = QTableWidget()
        self.outlet_table.setColumnCount(11)
        self.outlet_table.setHorizontalHeaderLabels([
            "ID", "网点名称", "类型", "设备总数", "已投放", "使用中", "故障",
            "订单数", "营收(元)", "平均时长(分)", "地址"
        ])
        self.outlet_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.outlet_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.outlet_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.outlet_table.doubleClicked.connect(self.view_outlet_detail)
        outlet_layout.addWidget(self.outlet_table)
        dashboard_layout.addWidget(outlet_group, 1)

        self.content_tabs.addTab(dashboard_page, "📊 运营看板")

        suggestion_page = QWidget()
        suggestion_layout = QVBoxLayout(suggestion_page)

        sug_btn_layout = QHBoxLayout()
        self.refresh_sug_btn = QPushButton("🔄 刷新建议")
        self.refresh_sug_btn.clicked.connect(self.load_suggestions)
        sug_btn_layout.addWidget(self.refresh_sug_btn)

        self.gen_plan_btn = QPushButton("📋 按选中建议生成投放计划")
        self.gen_plan_btn.clicked.connect(self.generate_plan_from_suggestions)
        sug_btn_layout.addWidget(self.gen_plan_btn)
        sug_btn_layout.addStretch()
        suggestion_layout.addLayout(sug_btn_layout)

        self.suggestion_table = QTableWidget()
        self.suggestion_table.setColumnCount(9)
        self.suggestion_table.setHorizontalHeaderLabels([
            "选择", "建议类型", "网点名称", "类型", "当前设备", "订单数",
            "建议数量", "营收(元)", "原因说明"
        ])
        self.suggestion_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.suggestion_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.suggestion_table.setEditTriggers(QTableWidget.NoEditTriggers)
        suggestion_layout.addWidget(self.suggestion_table, 1)

        self.content_tabs.addTab(suggestion_page, "💡 补货回收建议")

        main_layout.addWidget(self.content_tabs, 1)

    def load_data(self):
        location_types = self.service.get_location_types()
        cur = self.location_type_combo.currentData()
        self.location_type_combo.blockSignals(True)
        self.location_type_combo.clear()
        self.location_type_combo.addItem("全部", None)
        for t in location_types:
            self.location_type_combo.addItem(t, t)
        if cur is not None:
            idx = self.location_type_combo.findData(cur)
            if idx >= 0:
                self.location_type_combo.setCurrentIndex(idx)
        self.location_type_combo.blockSignals(False)

        outlets = self.service.get_all_outlets(self.location_type_combo.currentData())
        cur_outlet = self.outlet_combo.currentData()
        self.outlet_combo.blockSignals(True)
        self.outlet_combo.clear()
        self.outlet_combo.addItem("全部", None)
        for o in outlets:
            self.outlet_combo.addItem(o['name'], o['id'])
        if cur_outlet is not None:
            idx = self.outlet_combo.findData(cur_outlet)
            if idx >= 0:
                self.outlet_combo.setCurrentIndex(idx)
        self.outlet_combo.blockSignals(False)

        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")
        location_type = self.location_type_combo.currentData()
        outlet_id = self.outlet_combo.currentData()

        stats = self.service.get_overview_stats(start_date, end_date, location_type, outlet_id)
        for key, lbl in self.stat_labels.items():
            val = stats.get(key, 0) or 0
            if isinstance(val, float):
                lbl.setText(f"{val:.2f}")
            else:
                lbl.setText(str(val))

        outlet_stats = self.service.get_outlet_stats(start_date, end_date, location_type)
        if outlet_id:
            outlet_stats = [s for s in outlet_stats if s.get('outlet_id') == outlet_id]
        self.outlet_table.setRowCount(len(outlet_stats))
        for row, s in enumerate(outlet_stats):
            self.outlet_table.setItem(row, 0, QTableWidgetItem(str(s.get('outlet_id', ''))))
            self.outlet_table.setItem(row, 1, QTableWidgetItem(s.get('outlet_name', '')))
            self.outlet_table.setItem(row, 2, QTableWidgetItem(s.get('location_type') or '-'))
            self.outlet_table.setItem(row, 3, QTableWidgetItem(str(s.get('total_devices', 0))))
            self.outlet_table.setItem(row, 4, QTableWidgetItem(str(s.get('deployed', 0) or 0)))
            in_use_item = QTableWidgetItem(str(s.get('in_use', 0) or 0))
            in_use_item.setForeground(Qt.darkYellow)
            self.outlet_table.setItem(row, 5, in_use_item)
            faulty_item = QTableWidgetItem(str(s.get('faulty', 0) or 0))
            if (s.get('faulty', 0) or 0) > 0:
                faulty_item.setForeground(Qt.red)
            self.outlet_table.setItem(row, 6, faulty_item)
            self.outlet_table.setItem(row, 7, QTableWidgetItem(str(s.get('total_orders', 0) or 0)))
            rev_item = QTableWidgetItem(f"{s.get('total_revenue', 0):.2f}")
            rev_item.setForeground(Qt.darkGreen)
            self.outlet_table.setItem(row, 8, rev_item)
            avg_dur = s.get('avg_duration', 0) or 0
            self.outlet_table.setItem(row, 9, QTableWidgetItem(f"{avg_dur:.0f}"))
            self.outlet_table.setItem(row, 10, QTableWidgetItem(s.get('address') or '-'))

        self.load_suggestions()

    def load_suggestions(self):
        all_sugs = self.suggestion_service.get_all_suggestions()
        flat = []
        for key in ['low_stock', 'idle', 'high_fault']:
            flat.extend(all_sugs.get(key, []))

        self.suggestion_table.setRowCount(len(flat))
        self._suggestion_rows = flat
        for row, s in enumerate(flat):
            chk = QTableWidgetItem()
            chk.setFlags(chk.flags() | Qt.ItemIsUserCheckable)
            chk.setCheckState(Qt.Checked)
            self.suggestion_table.setItem(row, 0, chk)
            type_item = QTableWidgetItem(s.get('type_label', ''))
            type_map = {
                '⚠️ 低库存高需求': Qt.darkYellow,
                '📉 设备闲置': Qt.gray,
                '🚨 故障占比高': Qt.red
            }
            type_item.setForeground(type_map.get(s.get('type_label', ''), Qt.black))
            self.suggestion_table.setItem(row, 1, type_item)
            self.suggestion_table.setItem(row, 2, QTableWidgetItem(s.get('outlet_name', '')))
            self.suggestion_table.setItem(row, 3, QTableWidgetItem(s.get('location_type') or '-'))
            self.suggestion_table.setItem(row, 4, QTableWidgetItem(str(s.get('current_devices', 0) or 0)))
            self.suggestion_table.setItem(row, 5, QTableWidgetItem(str(s.get('order_count', 0) or 0)))
            qty_item = QTableWidgetItem(str(s.get('suggested_quantity', 0)))
            qty_item.setForeground(Qt.blue)
            self.suggestion_table.setItem(row, 6, qty_item)
            self.suggestion_table.setItem(row, 7, QTableWidgetItem(f"{s.get('total_revenue', 0):.2f}"))
            self.suggestion_table.setItem(row, 8, QTableWidgetItem(s.get('reason', '')))

    def view_outlet_detail(self):
        current_row = self.outlet_table.currentRow()
        if current_row < 0:
            return
        outlet_id = int(self.outlet_table.item(current_row, 0).text())
        outlet_name = self.outlet_table.item(current_row, 1).text()
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")
        dlg = OutletDetailDialog(self, outlet_id, outlet_name, self.service, start_date, end_date)
        dlg.exec_()

    def generate_plan_from_suggestions(self):
        selected = []
        for row in range(self.suggestion_table.rowCount()):
            item = self.suggestion_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                if row < len(self._suggestion_rows):
                    selected.append(self._suggestion_rows[row])

        if not selected:
            QMessageBox.warning(self, "提示", "请先勾选建议网点")
            return

        draft = self.suggestion_service.generate_plan_draft_from_suggestions(selected)
        if not draft:
            QMessageBox.warning(self, "提示", "选中的建议无法生成补货计划（闲置建议仅作提示）")
            return

        outlets = self.batch_service.get_all_outlets()
        outlets_by_type = {}
        for o in outlets:
            lt = o.get('location_type') or '其他'
            if lt not in outlets_by_type:
                outlets_by_type[lt] = []
            outlets_by_type[lt].append(o)

        dlg = PlanDialog(self, outlets_by_type)
        dlg.setWindowTitle("确认投放计划 (根据建议生成)")
        dlg.name_edit.setText(draft['plan_name'])
        idx = dlg.location_type_combo.findData(draft['location_type'])
        if idx >= 0:
            dlg.location_type_combo.setCurrentIndex(idx)
        dlg.target_total_spin.setValue(draft['target_quantity'])
        dlg.remark_edit.setText(draft.get('remark', '') or f"基于{len(selected)}条运营建议自动生成")
        dlg.operator_edit.setText(draft.get('operator', '') or '')

        for outlet_id, qty in draft.get('outlet_targets', []):
            if outlet_id in dlg.outlet_spins:
                dlg.outlet_spins[outlet_id].setValue(qty)
            else:
                for oid, spin in dlg.outlet_spins.items():
                    pass

        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            try:
                plan_id = self.plan_service.create_plan(**data)
                QMessageBox.information(self, "成功",
                    f"投放计划创建成功!\n计划ID: {plan_id}\n建议前往【拆分出库】->【投放计划】页执行出库")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"创建失败: {str(e)}")
