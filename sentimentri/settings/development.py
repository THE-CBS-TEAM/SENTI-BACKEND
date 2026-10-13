from .base import *
import os

DEBUG = True

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-only-key-not-for-production')

CORS_ALLOW_ALL_ORIGINS = True

# Add dev specific settings if necessary
ALLOWED_HOSTS = ['*']
