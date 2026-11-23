import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your_very_secret_key'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Mail Configuration
    MAIL_SERVER = 'smtppro.zoho.com'
    MAIL_PORT = 465
    MAIL_USE_SSL = True
    MAIL_USERNAME = 'noreply@ecometrix.co.in'
    MAIL_PASSWORD = 'fYxCByMsDwn4'
    MAIL_DEFAULT_SENDER = ('PMS Ecometrix', 'noreply@ecometrix.co.in')
    
    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_TYPE = 'redis'
    SESSION_REDIS = None  # Will be set in production

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///pms.db'

class ProductionConfig(Config):
    DEBUG = False
    # Use PostgreSQL for production
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'postgresql://user:password@localhost/pms_db'
    
    # Redis for session storage
    SESSION_REDIS = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    
    # Security settings
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
} 