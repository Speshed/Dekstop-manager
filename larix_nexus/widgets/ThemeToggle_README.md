# ThemeToggle Widget

Современный переключатель темы с анимированным бегунком и "пилюльной" формой.

## Функции

- ✨ Плавная анимация бегунка (180ms, OutCubic easing)
- 🎨 Современный дизайн с мягкими тенями
- 📐 Закругленная форма "пилюля"
- 🌙☀️ Иконки солнца и луны
- 🔍 Поддержка HiDPI (devicePixelRatio)
- ⌨️ Доступность с клавиатуры (Space, Enter)
- 🎯 Focus ring для навигации Tab
- 🖱️ Состояния hover/pressed

## API

```python
from larix_nexus.widgets.ThemeToggle import ThemeToggle

# Создание виджета
toggle = ThemeToggle()

# Состояние (True = dark, False = light)
toggle.isChecked()  # -> bool
toggle.setChecked(True)  # включить темную тему

# Переключение
toggle.toggle()

# Сигнал
toggle.toggled.connect(handler)  # сигнал toggled(bool)
```

## Использование в существующем окне

```python
from PySide6 import QtWidgets
from larix_nexus.widgets.ThemeToggle import ThemeToggle

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Создание переключателя темы
        self.theme_toggle = ThemeToggle()
        self.theme_toggle.toggled.connect(self.on_theme_toggled)
        
        # Начальное состояние (прочитать из настроек)
        self.theme_toggle.setChecked(self._is_dark_theme())
        
        # Добавление в layout
        central = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(central)
        layout.addWidget(self.theme_toggle)
        self.setCentralWidget(central)
    
    def on_theme_toggled(self, is_dark: bool):
        """Обработка переключения темы."""
        theme = "dark" if is_dark else "light"
        print(f"Тема изменена на: {theme}")
        
        # Применить тему к приложению
        app = QtWidgets.QApplication.instance()
        # Ваш код применения темы...
```

## Интеграция в PDF_Compare.py

Замена старого `ThemeSwitch` на новый `ThemeToggle` уже выполнена:

```python
# Импорт нового виджета
try:
    from larix_nexus.widgets.ThemeToggle import ThemeToggle
except ImportError:
    ThemeToggle = None

# Создание
if ThemeToggle is not None:
    self.theme_switch = ThemeToggle(icon_dir=ICON_DIR)
    hb.addWidget(self.theme_switch)
else:
    self.theme_switch = None

# Подключение сигналов
if self.theme_switch:
    self.theme_switch.toggled.connect(self._on_theme_toggled)
```

## Размеры и пропорции

- Размер по умолчанию: 160x64
- Иконка: 45% от высоты трека (~24px)
- Бегунок: высота трека - 8px
- Радиус скругления: 50% высоты (полный круг для бегунка)

## Цвета

### Темная тема (checked=True)
- Трек: #1c1c1e → #2c2c2e (градиент)
- Бегунок: #ffffff
- Иконка: #e0e0e0

### Светлая тема (checked=False)
- Трек: #f5f5f7 → #e8e8ec (градиент)
- Бегунок: #ffffff
- Иконка: #1a1a1a

## Требования

- PySide6
- Файлы иконок: `icon/sun.png` и `icon/moon.png`

## Лицензия

MIT License
