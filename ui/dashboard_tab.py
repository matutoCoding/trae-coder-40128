from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                             QPushButton, QDialog, QFormLayout, QLineEdit, QSpinBox,
                             QMessageBox, QHeaderView, QLabel, QGroupBox,
                             QDialogButtonBox, QDateEdit, QComboBox, QFrame,
                             QGridLayout, QSplitter, QCheckBox, QTabWidget, QDoubleSpinBox)
from PyQt5.QtCore import Qt, QDate, QRect, QPoint
from PyQt5.QtGui import QFont, QPainter, QPen, QColor
from services.dashboard_service import DashboardService
from services.suggestion_service import SuggestionService
from services.deployment_plan_service import DeploymentPlanService
from services.batch_service import BatchService


class TrendChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(280)
        self._data = []
        self._keys = []
        self._labels = []
        self._colors = []

    def setData(self, data_list, keys, labels=None, colors=None):
        self._data = data_list
        self._keys = keys
        self._labels = labels or keys
        default_colors = [QColor('#2c7be5'), QColor('#27ae60'), QColor('#f39c12'), QColor('#e74c3c')]
        self._colors = colors or default_colors[:len(keys)]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        margin_left = 70
        margin_right = 30
        margin_top = 30
        margin_bottom = 60
        chart_w = w - margin_left - margin_right
        chart_h = h - margin_top - margin_bottom

        painter.fillRect(self.rect(), QColor('#fafafa'))
        painter.setPen(QPen(QColor('#cccccc'), 1))
        painter.drawRect(margin_left, margin_top, chart_w, chart_h)

        if not self._data or len(self._data) < 2:
            painter.setPen(QColor('#999999'))
            painter.setFont(QFont('Microsoft YaHei', 11))
            painter.drawText(self.rect(), Qt.AlignCenter, '暂无趋势数据')
            painter.end()
            return

        n = len(self._data)

        all_vals = []
        for key in self._keys:
            for item in self._data:
                v = item.get(key, 0) or 0
                all_vals.append(v)

        if not all_vals:
            painter.end()
            return

        y_min = 0
        y_max = max(all_vals) if all_vals else 1
        if y_max == y_min:
            y_max = y_min + 1

        grid_count = 5
        painter.setPen(QPen(QColor('#e0e0e0'), 1, Qt.DotLine))
        painter.setFont(QFont('Microsoft YaHei', 8))
        for i in range(grid_count + 1):
            y_val = y_min + (y_max - y_min) * i / grid_count
            y_pos = margin_top + chart_h - int(chart_h * i / grid_count)
            painter.drawLine(margin_left, y_pos, margin_left + chart_w, y_pos)
            painter.setPen(QColor('#666666'))
            if y_max > 100:
                painter.drawText(QRect(0, y_pos - 10, margin_left - 5, 20), Qt.AlignRight | Qt.AlignVCenter,
                                 f'{int(y_val)}')
            else:
                painter.drawText(QRect(0, y_pos - 10, margin_left - 5, 20), Qt.AlignRight | Qt.AlignVCenter,
                                 f'{y_val:.1f}')
            painter.setPen(QPen(QColor('#e0e0e0'), 1, Qt.DotLine))

        step_x = chart_w / max(n - 1, 1)
        label_step = max(1, n // 10)
        painter.setPen(QColor('#666666'))
        for i in range(0, n, label_step):
            x_pos = margin_left + int(i * step_x)
            label = self._data[i].get('stat_week', '') or self._data[i].get('stat_date', '')
            if len(label) > 5:
                label = label[5:]
            painter.drawText(QRect(x_pos - 30, margin_top + chart_h + 5, 60, 20),
                             Qt.AlignCenter, label)

        for key_idx, key in enumerate(self._keys):
            color = self._colors[key_idx] if key_idx < len(self._colors) else QColor('#333333')
            painter.setPen(QPen(color, 2))
            points = []
            for i, item in enumerate(self._data):
                v = item.get(key, 0) or 0
                x = margin_left + int(i * step_x)
                ratio = (v - y_min) / (y_max - y_min) if y_max != y_min else 0
                y = margin_top + chart_h - int(chart_h * ratio)
                points.append(QPoint(x, y))
            for j in range(len(points) - 1):
                painter.drawLine(points[j], points[j + 1])
            painter.setBrush(color)
            for pt in points:
                painter.drawEllipse(pt, 3, 3)
            painter.setBrush(Qt.NoBrush)

        legend_y = h - 18
        legend_x = margin_left
        for key_idx, label in enumerate(self._labels):
            color = self._colors[key_idx] if key_idx < len(self._colors) else QColor('#333333')
            painter.setPen(QPen(color, 2))
            painter.drawLine(legend_x, legend_y, legend_x + 20, legend_y)
            painter.setPen(QColor('#333333'))
            painter.setFont(QFont('Microsoft YaHei', 9))
            painter.drawText(legend_x + 24, legend_y + 5, label)
            legend_x += len(label) * 9 + 44

        painter.end()


class PlanDraftDialog(QDialog):
    def __init__(self, parent=None, draft=None, plan_service=None):
        super().__init__(parent)
        self.setWindowTitle("调度计划草稿")
        self.setMinimumSize(800, 600)
        self.draft = draft or {}
        self.plan_service = plan_service
        self.outlet_spinboxes = []

        layout = QVBoxLayout(self)

        form_layout = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setText(self.draft.get('plan_name', ''))
        form_layout.addRow("计划名称:", self.name_edit)

        summary_parts = []
        rc = self.draft.get('restock_count', 0)
        rec = self.draft.get('recovery_count', 0)
        repc = self.draft.get('replace_count', 0)
        if rc:
            summary_parts.append(f"补货{rc}台")
        if rec:
            summary_parts.append(f"回收{rec}台")
        if repc:
            summary_parts.append(f"替换{repc}台")
        summary_label = QLabel(" / ".join(summary_parts) if summary_parts else "无")
        summary_label.setStyleSheet("font-weight: bold; color: #2c7be5;")
        form_layout.addRow("任务汇总:", summary_label)
        layout.addLayout(form_layout)

        self.draft_table = QTableWidget()
        self.draft_table.setColumnCount(5)
        self.draft_table.setHorizontalHeaderLabels([
            "网点名称", "类型", "任务类型", "建议数量", "原因"
        ])
        self.draft_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.draft_table, 1)

        outlets = self.draft.get('outlet_targets', [])
        task_type_labels = {'restock': '补货', 'recovery': '回收', 'replace': '替换'}
        self.draft_table.setRowCount(len(outlets))
        for row, target in enumerate(outlets):
            if len(target) >= 6:
                outlet_id, qty, task_type, outlet_name, loc_type, reason = target[:6]
            elif len(target) >= 3:
                outlet_id, qty, task_type = target[:3]
                outlet_name = ''
                loc_type = ''
                reason = ''
            else:
                continue

            self.draft_table.setItem(row, 0, QTableWidgetItem(outlet_name))
            self.draft_table.setItem(row, 1, QTableWidgetItem(loc_type))
            task_label = task_type_labels.get(task_type, task_type)
            task_item = QTableWidgetItem(task_label)
            if task_type == 'restock':
                task_item.setForeground(Qt.darkGreen)
            elif task_type == 'recovery':
                task_item.setForeground(Qt.gray)
            elif task_type == 'replace':
                task_item.setForeground(Qt.red)
            self.draft_table.setItem(row, 2, task_item)

            spin = QSpinBox()
            spin.setRange(0, 9999)
            spin.setValue(qty)
            spin.valueChanged.connect(self._update_alloc_summary)
            self.draft_table.setCellWidget(row, 3, spin)
            self.outlet_spinboxes.append((row, outlet_id, task_type, spin))

            self.draft_table.setItem(row, 4, QTableWidgetItem(reason))

        summary_hbox = QHBoxLayout()
        self.alloc_summary_label = QLabel()
        self.alloc_summary_label.setStyleSheet("font-weight: bold; color: #2c7be5; font-size: 13px;")
        summary_hbox.addWidget(self.alloc_summary_label)
        summary_hbox.addStretch()
        layout.addLayout(summary_hbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确认创建计划")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_alloc_summary()

    def _update_alloc_summary(self):
        restock_total = 0
        recovery_total = 0
        replace_total = 0

        for row, outlet_id, task_type, spin in self.outlet_spinboxes:
            qty = spin.value()
            if task_type == 'restock':
                restock_total += qty
            elif task_type == 'recovery':
                recovery_total += qty
            elif task_type == 'replace':
                replace_total += qty

        net_target = restock_total + replace_total - recovery_total
        self.alloc_summary_label.setText(
            f"已分配: 补货{restock_total}台/回收{recovery_total}台/替换{replace_total}台 | 净目标:{net_target}台"
        )

    def _on_accept(self):
        plan_name = self.name_edit.text().strip()
        if not plan_name:
            QMessageBox.warning(self, "提示", "请输入计划名称")
            return

        outlet_targets = []
        restock_total = 0
        recovery_total = 0
        replace_total = 0
        for row, outlet_id, task_type, spin in self.outlet_spinboxes:
            qty = spin.value()
            if qty <= 0:
                continue
            outlet_targets.append((outlet_id, qty, task_type))
            if task_type == 'restock':
                restock_total += qty
            elif task_type == 'recovery':
                recovery_total += qty
            elif task_type == 'replace':
                replace_total += qty

        if not outlet_targets:
            QMessageBox.warning(self, "提示", "没有有效的调度数量")
            return

        supply_total = restock_total + replace_total
        if supply_total > 0:
            target_quantity = max(supply_total - recovery_total, 0)
            confirm_msg = (f"分配汇总:\n"
                          f"  补货: {restock_total}台\n"
                          f"  替换: {replace_total}台\n"
                          f"  回收: {recovery_total}台\n"
                          f"  净目标 = 补货+替换-回收 = {target_quantity}台\n\n"
                          f"确认创建计划?")
            reply = QMessageBox.question(self, "确认净目标", confirm_msg,
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply != QMessageBox.Yes:
                return
        else:
            target_quantity = recovery_total

        try:
            plan_id = self.plan_service.create_plan(
                plan_name=plan_name,
                location_type=self.draft.get('location_type', '混合类型'),
                target_quantity=target_quantity,
                outlet_targets=outlet_targets,
                priority=self.draft.get('priority', 'high'),
                plan_date=self.draft.get('plan_date'),
                operator=self.draft.get('operator'),
                remark=self.draft.get('remark', '')
            )
            QMessageBox.information(self, "成功",
                                    f"调度计划创建成功!\n计划ID: {plan_id}\n建议前往【拆分出库】->【投放计划】页执行出库")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"创建失败: {str(e)}")


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

        trend_tab = QWidget()
        trend_layout = QVBoxLayout(trend_tab)

        trend_data = self.dashboard_service.get_trend_data(
            start_date=self.start_date, end_date=self.end_date,
            outlet_id=self.outlet_id
        )

        self.trend_table = QTableWidget()
        self.trend_table.setColumnCount(5)
        self.trend_table.setHorizontalHeaderLabels([
            "日期", "订单数", "营收", "使用中设备", "故障数"
        ])
        self.trend_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.trend_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.trend_table.setRowCount(len(trend_data))
        for row, d in enumerate(trend_data):
            label = d.get('stat_week', '') or d.get('stat_date', '')
            self.trend_table.setItem(row, 0, QTableWidgetItem(label))
            self.trend_table.setItem(row, 1, QTableWidgetItem(str(d.get('orders', 0))))
            self.trend_table.setItem(row, 2, QTableWidgetItem(f"{d.get('revenue', 0):.2f}"))
            self.trend_table.setItem(row, 3, QTableWidgetItem(str(d.get('in_use_devices', 0))))
            self.trend_table.setItem(row, 4, QTableWidgetItem(str(d.get('faulty_devices', 0))))
        trend_layout.addWidget(self.trend_table)

        self.trend_chart = TrendChartWidget()
        self.trend_chart.setData(
            trend_data,
            keys=['orders', 'revenue', 'in_use_devices', 'faulty_devices'],
            labels=['订单数', '营收', '使用中', '故障'],
            colors=[QColor('#2c7be5'), QColor('#27ae60'), QColor('#f39c12'), QColor('#e74c3c')]
        )
        trend_layout.addWidget(self.trend_chart, 1)
        tabs.addTab(trend_tab, "📈 趋势与周转")

        turnover = self.dashboard_service.get_outlet_turnover(
            self.outlet_id, self.start_date, self.end_date
        )
        turnover_group = QGroupBox("周转率")
        turnover_layout = QGridLayout(turnover_group)
        turnover_defs = [
            ('total_devices', '设备总数', '#2c7be5'),
            ('total_borrows', '借出次数', '#27ae60'),
            ('total_returns', '归还次数', '#8e44ad'),
            ('avg_borrow_duration', '平均借出时长(分)', '#f39c12'),
            ('turnover_rate', '周转率', '#e74c3c'),
        ]
        for idx, (key, name, color) in enumerate(turnover_defs):
            r, c = divmod(idx, 3)
            card = QFrame()
            card.setStyleSheet(f"QFrame {{ border: 1px solid #ddd; border-radius: 6px; background: white; }}")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 6, 10, 6)
            title_lbl = QLabel(name)
            title_lbl.setStyleSheet("color: #666; font-size: 11px;")
            val = turnover.get(key, 0) or 0
            if isinstance(val, float):
                val_text = f"{val:.2f}"
            else:
                val_text = str(val)
            value_lbl = QLabel(val_text)
            value_lbl.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: bold;")
            card_layout.addWidget(title_lbl)
            card_layout.addWidget(value_lbl)
            turnover_layout.addWidget(card, r, c)
        trend_layout.addWidget(turnover_group)

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
        self._workbench_rows = []
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
        self.location_type_combo.currentIndexChanged.connect(self._on_location_type_changed)
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

        self._init_dashboard_tab()
        self._init_trend_tab()
        self._init_workbench_tab()

        main_layout.addWidget(self.content_tabs, 1)

    def _init_dashboard_tab(self):
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

    def _init_trend_tab(self):
        trend_page = QWidget()
        trend_layout = QVBoxLayout(trend_page)

        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("粒度:"))
        self.granularity_combo = QComboBox()
        self.granularity_combo.addItem("按日", "daily")
        self.granularity_combo.addItem("按周", "weekly")
        self.granularity_combo.currentIndexChanged.connect(self._load_trend_data)
        ctrl_layout.addWidget(self.granularity_combo)
        ctrl_layout.addStretch()
        trend_layout.addLayout(ctrl_layout)

        splitter = QSplitter(Qt.Vertical)

        self.trend_table = QTableWidget()
        self.trend_table.setColumnCount(5)
        self.trend_table.setHorizontalHeaderLabels([
            "日期/周", "订单数", "营收", "使用中设备", "故障数"
        ])
        self.trend_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.trend_table.setEditTriggers(QTableWidget.NoEditTriggers)
        splitter.addWidget(self.trend_table)

        self.trend_chart = TrendChartWidget()
        splitter.addWidget(self.trend_chart)

        splitter.setSizes([300, 300])
        trend_layout.addWidget(splitter, 1)

        self.content_tabs.addTab(trend_page, "📈 趋势分析")

    def _init_workbench_tab(self):
        wb_page = QWidget()
        wb_layout = QVBoxLayout(wb_page)

        filter_row = QHBoxLayout()
        self.chk_restock = QCheckBox("☑补货建议")
        self.chk_restock.setChecked(True)
        self.chk_restock.stateChanged.connect(self._filter_workbench)
        filter_row.addWidget(self.chk_restock)

        self.chk_recovery = QCheckBox("☑回收建议")
        self.chk_recovery.setChecked(True)
        self.chk_recovery.stateChanged.connect(self._filter_workbench)
        filter_row.addWidget(self.chk_recovery)

        self.chk_replace = QCheckBox("☑故障替换建议")
        self.chk_replace.setChecked(True)
        self.chk_replace.stateChanged.connect(self._filter_workbench)
        filter_row.addWidget(self.chk_replace)

        filter_row.addStretch()

        self.refresh_wb_btn = QPushButton("🔄 刷新建议")
        self.refresh_wb_btn.clicked.connect(self.load_workbench)
        filter_row.addWidget(self.refresh_wb_btn)
        wb_layout.addLayout(filter_row)

        self.workbench_table = QTableWidget()
        self.workbench_table.setColumnCount(8)
        self.workbench_table.setHorizontalHeaderLabels([
            "选择", "建议类型", "网点名称", "类型", "当前设备", "建议数量", "营收(元)", "原因"
        ])
        self.workbench_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.workbench_table.setSelectionBehavior(QTableWidget.SelectRows)
        wb_layout.addWidget(self.workbench_table, 1)

        bottom_row = QHBoxLayout()
        self.wb_summary_label = QLabel("已选0条，补货0台/回收0台/替换0台")
        self.wb_summary_label.setStyleSheet("font-weight: bold; color: #2c7be5; font-size: 13px;")
        bottom_row.addWidget(self.wb_summary_label)
        bottom_row.addStretch()

        self.gen_draft_btn = QPushButton("📋 生成调度计划草稿")
        self.gen_draft_btn.clicked.connect(self._generate_draft)
        bottom_row.addWidget(self.gen_draft_btn)
        wb_layout.addLayout(bottom_row)

        self.content_tabs.addTab(wb_page, "🛠️ 调度工作台")

    def _on_location_type_changed(self):
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
        self._load_trend_data()

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

        self._load_trend_data()
        self.load_workbench()

    def _load_trend_data(self):
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")
        location_type = self.location_type_combo.currentData()
        outlet_id = self.outlet_combo.currentData()
        granularity = self.granularity_combo.currentData() or 'daily'

        trend_data = self.service.get_trend_data(
            start_date=start_date, end_date=end_date,
            location_type=location_type, outlet_id=outlet_id,
            granularity=granularity
        )

        self.trend_table.setRowCount(len(trend_data))
        for row, d in enumerate(trend_data):
            label = d.get('stat_week', '') or d.get('stat_date', '')
            self.trend_table.setItem(row, 0, QTableWidgetItem(label))
            self.trend_table.setItem(row, 1, QTableWidgetItem(str(d.get('orders', 0))))
            self.trend_table.setItem(row, 2, QTableWidgetItem(f"{d.get('revenue', 0):.2f}"))
            self.trend_table.setItem(row, 3, QTableWidgetItem(str(d.get('in_use_devices', 0))))
            self.trend_table.setItem(row, 4, QTableWidgetItem(str(d.get('faulty_devices', 0))))

        self.trend_chart.setData(
            trend_data,
            keys=['orders', 'revenue', 'in_use_devices', 'faulty_devices'],
            labels=['订单数(蓝)', '营收(绿)', '使用中(橙)', '故障(红)'],
            colors=[QColor('#2c7be5'), QColor('#27ae60'), QColor('#f39c12'), QColor('#e74c3c')]
        )

    def load_workbench(self):
        all_sugs = self.suggestion_service.get_all_suggestions()
        flat = []
        for key in ['low_stock', 'idle', 'high_fault']:
            flat.extend(all_sugs.get(key, []))
        self._workbench_rows = flat
        self._filter_workbench()

    def _filter_workbench(self):
        show_restock = self.chk_restock.isChecked()
        show_recovery = self.chk_recovery.isChecked()
        show_replace = self.chk_replace.isChecked()

        type_filter = {
            'low_stock_high_demand': show_restock,
            'idle': show_recovery,
            'high_fault': show_replace,
        }

        filtered = [s for s in self._workbench_rows if type_filter.get(s.get('suggestion_type'), True)]

        type_labels = {
            'low_stock_high_demand': '⚠️ 补货建议',
            'idle': '📉 回收建议',
            'high_fault': '🚨 故障替换建议',
        }
        type_colors = {
            'low_stock_high_demand': Qt.darkGreen,
            'idle': Qt.gray,
            'high_fault': Qt.red,
        }

        self.workbench_table.setRowCount(len(filtered))
        self._workbench_spins = []
        for row, s in enumerate(filtered):
            chk = QTableWidgetItem()
            chk.setFlags(chk.flags() | Qt.ItemIsUserCheckable)
            chk.setCheckState(Qt.Checked)
            self.workbench_table.setItem(row, 0, chk)

            tl = type_labels.get(s.get('suggestion_type', ''), s.get('type_label', ''))
            type_item = QTableWidgetItem(tl)
            type_item.setForeground(type_colors.get(s.get('suggestion_type', ''), Qt.black))
            self.workbench_table.setItem(row, 1, type_item)

            self.workbench_table.setItem(row, 2, QTableWidgetItem(s.get('outlet_name', '')))
            self.workbench_table.setItem(row, 3, QTableWidgetItem(s.get('location_type') or '-'))
            self.workbench_table.setItem(row, 4, QTableWidgetItem(str(s.get('current_devices', 0) or 0)))

            spin = QSpinBox()
            spin.setRange(0, 9999)
            spin.setValue(s.get('suggested_quantity', 0) or 0)
            self.workbench_table.setCellWidget(row, 5, spin)
            self._workbench_spins.append((row, s, spin))

            self.workbench_table.setItem(row, 6, QTableWidgetItem(f"{s.get('total_revenue', 0):.2f}"))
            self.workbench_table.setItem(row, 7, QTableWidgetItem(s.get('reason', '')))

        self._update_wb_summary()

    def _update_wb_summary(self):
        selected_count = 0
        restock_total = 0
        recovery_total = 0
        replace_total = 0

        type_map = {
            'low_stock_high_demand': 'restock',
            'idle': 'recovery',
            'high_fault': 'replace',
        }

        for row, s, spin in self._workbench_spins:
            chk = self.workbench_table.item(row, 0)
            if chk and chk.checkState() == Qt.Checked:
                selected_count += 1
                qty = spin.value()
                task_type = type_map.get(s.get('suggestion_type', ''), '')
                if task_type == 'restock':
                    restock_total += qty
                elif task_type == 'recovery':
                    recovery_total += qty
                elif task_type == 'replace':
                    replace_total += qty

        self.wb_summary_label.setText(
            f"已选{selected_count}条，补货{restock_total}台/回收{recovery_total}台/替换{replace_total}台"
        )

    def _generate_draft(self):
        selected = []
        type_map = {
            'low_stock_high_demand': 'restock',
            'idle': 'recovery',
            'high_fault': 'replace',
        }

        for row, s, spin in self._workbench_spins:
            chk = self.workbench_table.item(row, 0)
            if chk and chk.checkState() == Qt.Checked:
                s_copy = dict(s)
                s_copy['suggested_quantity'] = spin.value()
                selected.append(s_copy)

        if not selected:
            QMessageBox.warning(self, "提示", "请先勾选建议网点")
            return

        draft = self.suggestion_service.generate_workbench_draft(selected)
        if not draft:
            QMessageBox.warning(self, "提示", "选中的建议无法生成调度计划")
            return

        dlg = PlanDraftDialog(self, draft=draft, plan_service=self.plan_service)
        dlg.exec_()
        self._update_wb_summary()

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
