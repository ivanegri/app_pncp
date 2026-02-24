from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from .models import User
from functools import wraps

admin_bp = Blueprint('admin_bp', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Acesso negado. Área restrita a administradores.', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/admin/users')
@login_required
@admin_required
def list_users():
    users = User.get_all()
    return render_template('admin_users.html', users=users)

@admin_bp.route('/admin/user/<int:user_id>/update', methods=['POST'])
@login_required
@admin_required
def update_user_tier(user_id):
    user = User.get(user_id)
    if not user:
        abort(404)
        
    new_tier = request.form.get('tier')
    
    if new_tier in ['free', 'starter', 'full']:
        user.tier = new_tier
        try:
            user.save()
            flash(f'Plano do usuário {user.name or user.email} atualizado para {new_tier}.', 'success')
        except Exception as e:
            flash(f'Erro ao atualizar plano: {str(e)}', 'danger')
    else:
        flash('Plano inválido.', 'warning')
        
    return redirect(url_for('admin_bp.list_users'))
