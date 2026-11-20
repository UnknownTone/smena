"""Точка входа сборки PyInstaller: то же, что `python -m smena` (окно, --run-script, --selftest).
smena/__main__.py выполняется при импорте; прямой импорт нужен, чтобы PyInstaller увидел все модули."""
import smena.__main__  # noqa: F401
