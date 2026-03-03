from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAuthenticatedAndReadOnly(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.method in SAFE_METHODS)


class IsSuperUserRole(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.role == "superuser")


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, "profile", None)
        return bool(profile and profile.role in ["admin", "operator", "superuser"])


class IsBusinessAdminRole(BasePermission):
    """Permission for Business Admin (replaces IsBusinessOwnerRole)"""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        try:
            profile = getattr(request.user, "profile", None)
        except Exception:
            profile = None
        if not profile:
            return False
        role = getattr(profile, "role", None)
        # Support both business_admin and legacy business_owner
        return role in ["business_admin", "business_owner", "admin", "operator", "superuser"]


class IsBusinessOwnerRole(BasePermission):
    """Deprecated: use IsBusinessAdminRole instead. Kept for backward compatibility."""
    def has_permission(self, request, view):
        return IsBusinessAdminRole().has_permission(request, view)

# Alias for backward compatibility - use IsBusinessAdminRole in new code
IsBusinessOwnerRole = IsBusinessAdminRole


class IsCustomerRole(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, "profile", None)
        # Customer role is only for Loyalty app, not Menu app
        return bool(profile and profile.role in ["customer", "business_admin", "business_owner", "admin", "operator", "superuser"])


class IsOwnerOrSuperUser(BasePermission):
    """
    Custom permission to only allow owners of an object or superusers to edit it.
    """
    def has_object_permission(self, request, view, obj):
        # Superusers can do anything
        profile = getattr(request.user, "profile", None)
        if profile and profile.role == "superuser":
            return True
        
        # Business admins can edit their own objects
        if hasattr(obj, 'user'):
            return obj.user == request.user
        elif hasattr(obj, 'business_admin') and obj.business_admin:
            return obj.business_admin.user == request.user
        elif hasattr(obj, 'owner'):  # Legacy support
            return obj.owner == request.user
        
        return False


class CanManageUsers(BasePermission):
    """
    Permission to manage users - only superusers can manage all users,
    admins can manage business admins and customers
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        profile = getattr(request.user, "profile", None)
        if not profile:
            return False
        
        # Superusers can manage everyone
        if profile.role == "superuser":
            return True
        
        # Admins can manage business admins and customers
        if profile.role in ["admin", "operator"]:
            return True
        
        return False
