"""Role constants for the four-tier auth model.

Two storage tables back the four roles:

* ``vendor_admin`` -> ``VendorUser`` (platform-level admin)
* ``tenant_admin``, ``tenant_user``, ``solo_user`` -> ``User`` (tenant accounts)

The ``role`` value is embedded in every JWT claim and used to gate access to
role-specific dashboards.
"""
from __future__ import annotations


class Roles:
    VENDOR_ADMIN = "vendor_admin"
    TENANT_ADMIN = "tenant_admin"
    TENANT_USER = "tenant_user"
    SOLO_USER = "solo_user"

    ALL = (VENDOR_ADMIN, TENANT_ADMIN, TENANT_USER, SOLO_USER)

    @classmethod
    def is_valid(cls, role: str) -> bool:
        return role in cls.ALL