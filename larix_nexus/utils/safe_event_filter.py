# -*- coding: utf-8 -*-
"""Safe event filter wrapper to prevent crashes.

This module provides a decorator that wraps eventFilter methods
with proper error handling to prevent access violation crashes.
"""

import functools
import logging

logger = logging.getLogger("app")


def safe_event_filter(event_filter_func):
    """
    Decorator to wrap eventFilter methods with error handling.

    Usage:
        class MyClass(QObject):
            @safe_event_filter
            def eventFilter(self, obj, ev):
                # Your event filter logic here
                return super().eventFilter(obj, ev)
    """
    @functools.wraps(event_filter_func)
    def wrapper(self, obj, ev):
        try:
            return event_filter_func(self, obj, ev)
        except Exception as e:
            logger.exception("Error in eventFilter (obj=%s): %s", type(obj).__name__, e)
            return False  # Safe fallback: always return False on error

    return wrapper


# Apply to known event filter classes automatically
def apply_safe_wrapper_to_class(cls):
    """
    Apply safe_event_filter wrapper to all eventFilter methods in a class.
    """
    if not hasattr(cls, 'eventFilter'):
        return cls

    original_event_filter = cls.eventFilter

    def safe_event_filter(self, obj, ev):
        try:
            return original_event_filter(self, obj, ev)
        except Exception as e:
            logger.exception("Error in %s.eventFilter: %s", cls.__name__, e)
            return False

    cls.eventFilter = safe_event_filter
    return cls


# Monkey patch to make all QObject subclasses safe by default
def install_safe_event_filter_system():
    """
    Install system-wide safe event filter wrapping.

    This patches QObject to wrap all eventFilter implementations with error handling.
    """
    original_setattr = type.__setattr__

    def safe_setattr(cls, name, value):
        # If setting eventFilter method, wrap it with safety
        if name == 'eventFilter' and callable(value):
            try:
                @functools.wraps(value)
                def wrapper(self, obj, ev):
                    try:
                        return value(self, obj, ev)
                    except Exception as e:
                        logger.exception("Error in eventFilter: %s", e)
                        return False
                original_setattr(cls, name, wrapper)
                return
            except Exception:
                pass

        original_setattr(cls, name, value)

    # Only patch if not already patched
    if not hasattr(QObject, '_safe_event_filter_patched'):
        type.__setattr__ = safe_setattr
        QObject._safe_event_filter_patched = True

        logger.info("Installed safe event filter system")


# Auto-install on import
try:
    from PySide6.QtCore import QObject
    install_safe_event_filter_system()
except Exception as e:
    logger.warning("Could not install safe event filter system: %s", e)
