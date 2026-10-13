import os
from pathlib import Path
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Initialize environment variables
env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str),
    ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
    DATABASE_URL=(str, 'postgres://sentimentri:sentimentri_pass@db:5432/sentimentri_db'),
    REDIS_URL=(str, 'redis://redis:6379/0'),
    APIFY_API_TOKEN=(str, ''),
    SOCIALDATA_API_KEY=(str, ''),
    DAILY_CREDIT_BUDGET_CAP=(float, 50.00),
)

# Read .env file if it exists (at BASE_DIR / '../.env' or BASE_DIR / '.env')
env_file_path = BASE_DIR.parent / '.env'
if env_file_path.exists():
    environ.Env.read_env(str(env_file_path))
else:
    local_env = BASE_DIR / '.env'
    if local_env.exists():
        environ.Env.read_env(str(local_env))

SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env('ALLOWED_HOSTS')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    
    # Third party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    
    # Project apps
    'apps.accounts.apps.AccountsConfig',
    'apps.influencers.apps.InfluencersConfig',
    'apps.campaigns.apps.CampaignsConfig',
    'apps.sentiment.apps.SentimentConfig',
    'apps.scoring.apps.ScoringConfig',
    'apps.reports.apps.ReportsConfig',
    'apps.admin_panel.apps.AdminPanelConfig',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sentimentri.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'sentimentri.wsgi.application'
ASGI_APPLICATION = 'sentimentri.asgi.application'

# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
DATABASES = {
    'default': env.db('DATABASE_URL')
}

# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}

# CORS settings
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
    'http://localhost:3000',
    'http://127.0.0.1:3000',
])
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[
    'http://localhost:3000',
    'http://127.0.0.1:3000',
])

# JWT Configuration
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Celery Configuration
from celery.schedules import crontab

CELERY_BROKER_URL = env('REDIS_URL')
CELERY_RESULT_BACKEND = env('REDIS_URL')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_IMPORTS = (
    'tasks.fetch_tasks',
    'tasks.scoring_tasks',
    'tasks.sentiment_tasks',
    'tasks.report_tasks',
    'tasks.influencer_tasks',
)

CELERY_BEAT_SCHEDULE = {
    # Post monitoring: Hourly check that ONLY polls posts whose user-configured interval
    # (set in Workspace Settings: T1, T2, T3 interval hours) has elapsed (next_poll_at <= now).
    'poll-active-posts-by-user-schedule': {
        'task': 'tasks.fetch_tasks.poll_active_posts_scheduled',
        'schedule': timedelta(hours=1),
    },
    # Note: Influencer freshness checks and Centi score recalculations are strictly
    # manual to conserve API credits, triggered ONLY when the user clicks 'Recalculate'.
}

# Third Party API Integration Keys
APIFY_API_TOKEN = env('APIFY_API_TOKEN', default='')
SOCIALDATA_API_KEY = env('SOCIALDATA_API_KEY', default='')
DEEP_SEEK_SECRET = env('DEEP_SEEK_SECRET', default='')

# SociaVault — unified social media data API (replaces Apify + SocialData)
SOCIAL_VAULT_API_KEY = env('SOCIAL_VAULT_API_KEY', default='')

# Budget Caps
DAILY_CREDIT_BUDGET_CAP = env('DAILY_CREDIT_BUDGET_CAP')

# Role-Specific Admin Registration Keys (Legacy — will be deprecated after invite system ships)
SUPER_ADMIN_ACCESS_KEY = env('SUPER_ADMIN_ACCESS_KEY', default='')
DEVELOPER_ACCESS_KEY = env('DEVELOPER_ACCESS_KEY', default='')
SUPPORT_ACCESS_KEY = env('SUPPORT_ACCESS_KEY', default='')
WEBHOOK_SECRET = env('WEBHOOK_SECRET', default='')

# Frontend URL — used in invitation email links
FRONTEND_URL = env('FRONTEND_URL', default='http://localhost:3000')

# ─── Email Configuration ───────────────────────────────────────────────────────
# Development: emails are printed to the console so no SMTP setup is needed.
# Production: swap EMAIL_BACKEND to 'django.core.mail.backends.smtp.EmailBackend'
#             and set MAILJET_API_KEY / MAILJET_SECRET_KEY in .env, then wire up
#             the apps.core.services.email helper to use the Mailjet REST API or
#             Mailjet's SMTP relay (smtp.mailjet.com:587).
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='Sentimentri <noreply@sentimentri.com>')
EMAIL_HOST = env('EMAIL_HOST', default='smtp.mailjet.com')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('MAILJET_API_KEY', default='')
EMAIL_HOST_PASSWORD = env('MAILJET_SECRET_KEY', default='')
