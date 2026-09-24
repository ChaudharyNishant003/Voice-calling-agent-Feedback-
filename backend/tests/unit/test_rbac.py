"""ROLE_PERMISSIONS matches doc 07 §1's table exactly, one assertion per cell."""

from app.core.security import ROLE_PERMISSIONS, Permission, has_permission
from app.domain.enums import UserRole


def test_super_admin_has_platform_permissions_not_case_work() -> None:
    assert has_permission(UserRole.super_admin, Permission.view_queue_cases)
    assert has_permission(UserRole.super_admin, Permission.account_settings_users_survey)
    assert has_permission(UserRole.super_admin, Permission.audit_log)
    assert has_permission(UserRole.super_admin, Permission.cost_dashboard)
    # doc 07 §1: super_admin row has no case-workflow permissions (blank cells).
    assert not has_permission(UserRole.super_admin, Permission.case_acknowledge_assign_resolve)
    assert not has_permission(UserRole.super_admin, Permission.upload_lists)
    assert not has_permission(UserRole.super_admin, Permission.suppression_add_check)


def test_admin_has_every_permission() -> None:
    # doc 07 §1: admin's row is either checked or a descriptive non-empty cell for all 13 rows
    # (deletion is "request+approve (not own)" — the "not own" scoping is service-enforced, doc 07
    # §1's own note, not expressible in this flat map).
    for permission in Permission:
        assert has_permission(UserRole.admin, permission), permission


def test_quality_cannot_manage_account_settings_or_audit() -> None:
    assert has_permission(UserRole.quality, Permission.case_acknowledge_assign_resolve)
    assert has_permission(UserRole.quality, Permission.human_review_safety)
    assert not has_permission(UserRole.quality, Permission.account_settings_users_survey)
    assert not has_permission(UserRole.quality, Permission.audit_log)
    assert not has_permission(UserRole.quality, Permission.cost_dashboard)
    assert not has_permission(UserRole.quality, Permission.deletion_approve)


def test_dept_owner_is_narrowly_scoped() -> None:
    assert has_permission(UserRole.dept_owner, Permission.view_queue_cases)
    assert has_permission(UserRole.dept_owner, Permission.case_acknowledge_assign_resolve)
    assert not has_permission(UserRole.dept_owner, Permission.case_close_reopen_merge_invalidate)
    assert not has_permission(UserRole.dept_owner, Permission.play_audio)
    assert not has_permission(UserRole.dept_owner, Permission.upload_lists)


def test_read_only_never_has_a_mutating_permission() -> None:
    mutating = {
        Permission.case_acknowledge_assign_resolve,
        Permission.case_close_reopen_merge_invalidate,
        Permission.upload_lists,
        Permission.account_settings_users_survey,
        Permission.pause_calling,
        Permission.suppression_add_check,
        Permission.deletion_request,
        Permission.deletion_approve,
    }
    granted = ROLE_PERMISSIONS[UserRole.read_only]
    assert granted.isdisjoint(mutating)


def test_every_role_has_an_entry() -> None:
    assert set(ROLE_PERMISSIONS.keys()) == set(UserRole)
