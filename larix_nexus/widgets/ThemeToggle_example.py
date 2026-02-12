# ThemeToggle - готовое решение
# Файл: larix_nexus/widgets/ThemeToggle.py

"""Пример интеграции ThemeToggle в существующее окно."""

from PySide6 import QtWidgets, QtCore
from larix_nexus.widgets.ThemeToggle import ThemeToggle

# В вашем классе окна:
class MyWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 1. Создать переключатель темы
        self.theme_toggle = ThemeToggle()
        
        # 2. Подключить сигнал toggled
        self.theme_toggle.toggled.connect(self.on_theme_changed)
        
        # 3. Установить начальное состояние (опционально)
        saved_theme = load_saved_theme()  # ваша функция загрузки
        self.theme_toggle.setChecked(saved_theme == "dark", animate=False)
        
        # 4. Добавить в layout
        central = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(central)
        layout.addWidget(self.theme_toggle)
        self.setCentralWidget(central)
    
    def on_theme_changed(self, is_dark: bool):
        """Обработчик переключения темы."""
        theme = "dark" if is_dark else "light"
        print(f"Тема изменена на: {theme}")
        
        # Применить тему
        from larix_nexus.pdf.PDF_Compare import apply_dekstop_style
        app = QtWidgets.QApplication.instance()
        apply_dekstop_style(app, dark=is_dark, target=self)
        
        # Сохранить выбор
        save_theme(theme)  # ваша функция сохранения

# Пример для standalone виджета:
if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    
    toggle = ThemeToggle()
    toggle.show()
    
    sys.exit(app.exec())
