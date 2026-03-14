from django.contrib.auth.base_user import BaseUserManager
from django.utils import timezone

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('email must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('email_verified', True)
        return self.create_user(email, password, **extra_fields)
    
    def get_active_users(self):
        return self.filter(is_suspended=False, email_verified=True)
    
    def get_pending_deletion(self):
        return self.filter(
            deletion_scheduled_for__lte=timezone.now(),
            deletion_scheduled_for__isnull=False
        )