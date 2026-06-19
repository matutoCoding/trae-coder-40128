from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QTabWidget, QStatusBar, QMenuBar, QAction, QMessageBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from ui.billing_tab import BillingTab
from ui.batch_tab import BatchTab
from ui.outbound_tab import OutboundTab
from ui.rental_tab import RentalTab


class MainWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("共享充电宝投放管理系统")
        self.setMinimumSize(1280, 800)

        self.init_ui()
        self.init_menu()
        self.init_status_bar()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        header_layout = QHBoxLayout()
        title_label = QLabel("共享充电宝投放管理系统")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #2c7be5;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.user_label = QLabel("管理员")
        self.user_label.setStyleSheet("color: #666;")
        header_layout.addWidget(self.user_label)

        main_layout.addLayout(header_layout)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #ddd;
                top: -1px;
            }
            QTabBar::tab {
                background: #f5f5f5;
                border: 1px solid #ddd;
                padding: 8px 20px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: white;
                border-bottom-color: white;
                color: #2c7be5;
                font-weight: bold;
            }
        """)

        self.billing_tab = BillingTab(self.db)
        self.batch_tab = BatchTab(self.db)
        self.outbound_tab = OutboundTab(self.db)
        self.rental_tab = RentalTab(self.db)

        self.tab_widget.addTab(self.billing_tab, "💰 计费规则")
        self.tab_widget.addTab(self.batch_tab, "📦 设备批次")
        self.tab_widget.addTab(self.outbound_tab, "🚚 拆分出库")
        self.tab_widget.addTab(self.rental_tab, "📊 账单生成")

        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        main_layout.addWidget(self.tab_widget, 1)

    def init_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件(&F)")

        refresh_action = QAction("刷新数据(&R)", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_all)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&Q)", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def init_status_bar(self):
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        status_bar.showMessage("就绪")

        self.summary_label = QLabel()
        status_bar.addPermanentWidget(self.summary_label)
        self.update_summary()

    def on_tab_changed(self, index):
        if index == 0:
            self.billing_tab.load_data()
        elif index == 1:
            self.batch_tab.load_data()
        elif index == 2:
            self.outbound_tab.load_data()
        elif index == 3:
            self.rental_tab.load_data()

    def refresh_all(self):
        self.billing_tab.load_data()
        self.batch_tab.load_data()
        self.outbound_tab.load_data()
        self.rental_tab.load_data()
        self.update_summary()
        self.statusBar().showMessage("数据已刷新", 3000)

    def update_summary(self):
        from services.batch_service import BatchService
        from services.rental_service import RentalService

        batch_service = BatchService(self.db)
        rental_service = RentalService(self.db)

        dist_summary = batch_service.get_distribution_summary()
        rental_summary = rental_service.get_rental_summary()

        total_devices = dist_summary.get('total_devices', 0) or 0
        deployed = dist_summary.get('deployed', 0) or 0
        total_revenue = rental_summary.get('total_revenue', 0) or 0
        active_orders = rental_summary.get('active_orders', 0) or 0

        self.summary_label.setText(
            f"  总设备: {total_devices} | "
            f"已投放: {deployed} | "
            f"使用中: {active_orders} | "
            f"累计营收: {total_revenue:.2f}元  "
        )

    def show_about(self):
        QMessageBox.about(self, "关于",
            """<h2>共享充电宝投放管理系统</h2>
            <p>版本: 1.0.0</p>
            <p>功能模块:</p>
            <ul>
                <li>💰 计费规则 - 规则配置、起步价计算、封顶价拦截</li>
                <li>📦 设备批次 - 批次管理、剩余量追踪</li>
                <li>🚚 拆分出库 - 批次拆分、去向分布记录</li>
                <li>📊 账单生成 - 租借计费、账单生成、坏宝锁定</li>
            </ul>
            <p>技术栈: Python + PyQt5 + SQLite</p>
            """)

    def closeEvent(self, event):
        reply = QMessageBox.question(self, "确认退出",
            "确定要退出系统吗?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            self.db.close()
            event.accept()
        else:
            event.ignore()
