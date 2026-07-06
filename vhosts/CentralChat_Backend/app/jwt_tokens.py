"""Compatibility module for JWT helpers now implemented in app.auth."""

from __future__ import annotations

import sys

from app import auth as _auth

sys.modules[__name__] = _auth
