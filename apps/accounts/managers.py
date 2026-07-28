from django.contrib.auth.base_user import BaseUserManager
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, full_name, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        if not full_name:
            raise ValueError('Full name is required')
        
        email = self.normalize_email(email)
        user = self.model(email=email, full_name=full_name, **extra_fields)
        user.set_password(password)
        user.username = email
        user.save(using=self._db)
        return user

    def create_superuser(self, email, full_name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('email_verified', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, full_name, password, **extra_fields)
    
    def get_active_users(self):
        return self.filter(
            is_suspended=False, 
            email_verified=True,
            is_active=True
        ).select_related()
    
    def get_clients(self):
        return self.filter(role='client').select_related()
    
    def get_admins(self):
        return self.filter(role='admin').select_related()
    
    def get_pending_deletion(self):
        return self.filter(
            deletion_scheduled_for__lte=timezone.now(),
            deletion_scheduled_for__isnull=False,
            is_active=True
        ).select_related()
    
    def get_locked_accounts(self):
        return self.filter(
            account_locked_until__gt=timezone.now(),
            is_active=True
        ).select_related()
    
    def get_suspended_accounts(self):
        return self.filter(
            is_suspended=True,
            is_active=True
        ).select_related()
    
    def get_unverified_users(self):
        return self.filter(
            email_verified=False,
            is_active=True,
            created_at__gte=timezone.now() - timezone.timedelta(days=7)
        ).select_related()
    
    def authenticate_user(self, email, password):
        try:
            user = self.get(email=email)
            if user.check_password(password):
                return user
        except self.model.DoesNotExist:
            return None
        return None
    
    def get_by_google_id(self, google_id):
        try:
            return self.get(google_id=google_id)
        except self.model.DoesNotExist:
            return None
    
    def create_google_user(self, email, full_name, google_id, picture='', **extra_fields):
        extra_fields.setdefault('role', 'client')
        extra_fields.setdefault('email_verified', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('google_id', google_id)
        extra_fields.setdefault('picture', picture)
        
        if not email:
            raise ValueError('Email is required')
        
        email = self.normalize_email(email)
        
        # Check if user already exists with this email
        user = self.filter(email=email).first()
        if user:
            if not user.google_id:
                user.google_id = google_id
                user.picture = picture
                user.save(update_fields=['google_id', 'picture'])
            return user
        
        # Create new user with a random password
        password = self.model.objects.make_random_password()
        user = self.model(email=email, full_name=full_name, google_id=google_id, picture=picture, **extra_fields)
        user.set_password(password)
        user.username = email
        user.save(using=self._db)
        return user