"""Python 3.14 compatibility patches for third-party packages.

Python 3.14 introduced a breaking change: ``super()`` objects no longer expose
a ``__dict__`` that can be read or written. Several libraries in the ecosystem
rely on the old behaviour, most notably Django's template ``Context.__copy__``
which calls ``copy.copy(super())`` — this fails with::

    'super' object has no attribute '__dict__'


Usage
-----
Call ``apply_py314_patches()`` early in the Django startup process
(typically at the end of ``settings/base.py``). The function is idempotent.

Extend this module as new Python 3.14 incompatibilities surface upstream.
"""

from __future__ import annotations

import copy
import logging

logger = logging.getLogger(__name__)

_PATCHES_APPLIED = False


def apply_py314_patches() -> None:
    """Apply all known Python 3.14 compatibility patches.

    Idempotent — safe to call multiple times from different entry points.
    """
    global _PATCHES_APPLIED
    if _PATCHES_APPLIED:
        return
    _patch_django_context_copy()
    _PATCHES_APPLIED = True


# ─── Django template Context.__copy__ ───────────────────────────────


def _patch_django_context_copy() -> None:
    """Patch ``django.template.context.Context.__copy__`` so it works with
    Python 3.14's stricter ``super()``.

    Django 5.1's ``Context.__copy__`` (inherited by ``RequestContext``) calls::

        duplicate = super().__copy__()

    …which invokes ``copy.copy(super())`` under Python 3.14 and crashes
    because ``super()`` has no ``__dict__``.  The fix is straightforward:
    since ``Context`` is a plain ``object`` subclass without its own
    ``__copy__``, we provide one that creates a shallow copy of ``self``
    directly instead of delegating to ``super().__copy__()``.
    """
    import django.template.context

    Context = django.template.context.Context

    # Only patch if the existing __copy__ would fail.
    existing = Context.__copy__
    if existing.__qualname__ != "Context.__copy__":
        # Someone already patched — skip.
        return

    def _safe_copy(self):
        """Standard shallow-copy for a plain object.

        Create a new instance and copy ``__dict__`` manually, bypassing
        Python 3.14's removal of ``super().__dict__``.
        """
        cls = type(self)
        duplicate = cls.__new__(cls)
        object.__setattr__(duplicate, "__dict__", copy.copy(self.__dict__))
        return duplicate

    # We apply the patch at the class level so all subclasses
    # (RequestContext, etc.) benefit automatically.
    Context.__copy__ = _safe_copy
    logger.debug("Applied Python 3.14 compat patch: django.template.context.Context.__copy__")
