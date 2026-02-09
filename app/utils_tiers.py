from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user

TIER_LEVELS = {
    'free': 0,
    'starter': 1,
    'full': 2,
    'admin': 3 
}

def get_tier_level(tier):
    return TIER_LEVELS.get(tier, 0)

def requires_tier(min_tier):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth_bp.login'))
            
            user_tier = current_user.tier or 'free'
            # Treat admin as full access
            if current_user.role == 'admin':
                user_level = 3
            else:
                user_level = get_tier_level(user_tier)
                
            required_level = get_tier_level(min_tier)
            
            if user_level < required_level:
                flash(f'Recurso disponível apenas no plano {min_tier.upper()}. Atualize seu plano!', 'warning')
                return redirect(url_for('main.pricing'))
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def check_tier_access(feature):
    """
    Centralized check for features not tied to a single route.
    Returns True if allowed, False otherwise.
    """
    if not current_user.is_authenticated:
        return False
        
    user_tier = current_user.tier or 'free'
    if current_user.role == 'admin':
        return True # Admin access all
        
    if feature == 'market_analysis':
        return user_tier == 'full'
        
    if feature == 'download_single':
        return user_tier in ['starter', 'full']
        
    if feature == 'download_zip':
        return user_tier == 'full'
        
    if feature == 'unlimited_search':
        return user_tier in ['starter', 'full']
        
    return False
