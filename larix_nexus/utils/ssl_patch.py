# -*- coding: utf-8 -*-
"""
SSL Patching Module for Windows + Python 3.13

This module MUST be imported before any other modules that use requests or urllib3.
It patches ssl.SSLContext and other SSL-related functions to prevent access violation
crashes when SSL handshake occurs in multithreaded environment (Qt background threads).
"""

import ssl
import sys

# ============================================================================
# Patch 1: Default HTTPS context
# ============================================================================
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

# ============================================================================
# Patch 2: Intercept ssl.create_default_context
# ============================================================================
_original_create_default_context = ssl.create_default_context
def _patched_create_default_context(*args, **kwargs):
    context = _original_create_default_context(*args, **kwargs)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
ssl.create_default_context = _patched_create_default_context

# ============================================================================
# Patch 3: Patch ssl.SSLContext to force verification off
# ============================================================================
if hasattr(ssl, 'SSLContext'):
    _original_ssl_context_new = ssl.SSLContext.__new__
    def _patched_ssl_context_new(cls, *args, **kwargs):
        instance = _original_ssl_context_new(cls, *args, **kwargs)
        # Force verification off
        instance.check_hostname = False
        instance.verify_mode = ssl.CERT_NONE
        return instance
    ssl.SSLContext.__new__ = _patched_ssl_context_new

# ============================================================================
# Patch 4: Patch ssl.wrap_socket
# ============================================================================
if hasattr(ssl, 'wrap_socket'):
    _original_wrap_socket = ssl.wrap_socket
    def _patched_wrap_socket(sock, *args, **kwargs):
        kwargs.setdefault('ssl_version', ssl.PROTOCOL_TLS)
        kwargs.setdefault('cert_reqs', ssl.CERT_NONE)
        kwargs.setdefault('check_hostname', False)
        return _original_wrap_socket(sock, *args, **kwargs)
    ssl.wrap_socket = _patched_wrap_socket

print('[SSL_PATCH] SSL patching applied successfully')
