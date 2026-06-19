import sys
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow
from db.database import Database


def main():
    app = QApplication(sys.argv)
    db = Database()
    db.init_database()
    window = MainWindow(db)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
