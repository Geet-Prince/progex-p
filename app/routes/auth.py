# ==============================================================================
# Authentication Routes
# ------------------------------------------------------------------------------
# This file handles the entire user authentication lifecycle, including
# email/password flows and the new Google Sign-In provider flow.
# ==============================================================================

import random
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from app.services import firebase_service, leetcode_api, email_service
from firebase_admin import auth as firebase_admin_auth

bp = Blueprint('auth', __name__)

# --- Standard Email/Password Routes ---

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('leetcode_username', '').lower()
        email = request.form.get('email', '').lower()
        if not username or not email:
            flash('Username and email are required.', 'error')
            return redirect(url_for('auth.register'))
        if firebase_service.get_user_data(username) or firebase_service.get_user_by_email(email):
            flash('A user with that LeetCode username or email already exists.', 'error')
            return redirect(url_for('auth.register'))
        if not leetcode_api.get_user_stats(username):
            flash('This LeetCode username could not be found.', 'error')
            return redirect(url_for('auth.register'))
        otp = str(random.randint(100000, 999999))
        firebase_service.create_unverified_user(username, email, otp)
        email_service.send_otp_email(email, otp)
        session['verifying_username'] = username
        flash('A verification code has been sent to your email.', 'info')
        return redirect(url_for('auth.verify'))
    return render_template('register.html')


@bp.route('/verify', methods=['GET', 'POST'])
def verify():
    username = session.get('verifying_username')
    if not username:
        return redirect(url_for('auth.register'))
    if request.method == 'POST':
        otp = request.form.get('otp')
        password = request.form.get('password')
        user_data = firebase_service.get_user_data(username)
        if user_data and user_data.get('otp') == otp:
            password_hash = generate_password_hash(password)
            firebase_service.verify_user_and_set_password(username, password_hash)
            session.pop('verifying_username', None)
            session['leetcode_username'] = username
            flash('Account verified successfully! You are now logged in.', 'success')
            return redirect(url_for('dashboard.user_dashboard'))
        else:
            flash('Invalid OTP. Please try again.', 'error')
    return render_template('verify.html')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').lower()
        password = request.form.get('password')
        user_data = firebase_service.get_user_by_email(email)
        if user_data and user_data.get('is_verified') and check_password_hash(user_data.get('password_hash', ''), password):
            session['leetcode_username'] = user_data['leetcode_username']
            return redirect(url_for('dashboard.user_dashboard'))
        else:
            flash('Invalid email or password.', 'error')
    return render_template('login.html')


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').lower()
        user_data = firebase_service.get_user_by_email(email)
        if user_data:
            username = user_data['leetcode_username']
            otp = str(random.randint(100000, 999999))
            firebase_service.set_password_reset_otp(username, otp)
            email_service.send_password_reset_email(email, otp)
        session['resetting_email'] = email
        flash('If an account with that email exists, a password reset code has been sent.', 'info')
        return redirect(url_for('auth.reset_password'))
    return render_template('forgot_password.html')


@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    email = session.get('resetting_email')
    if not email:
        return redirect(url_for('auth.forgot_password'))
    if request.method == 'POST':
        otp = request.form.get('otp')
        new_password = request.form.get('password')
        user_data = firebase_service.get_user_by_email(email)
        if user_data and user_data.get('reset_otp') == otp:
            new_password_hash = generate_password_hash(new_password)
            firebase_service.reset_password(user_data['leetcode_username'], new_password_hash)
            session.pop('resetting_email', None)
            flash('Your password has been successfully reset. Please log in.', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash('Invalid OTP. Please try again.', 'error')
    return render_template('reset_password.html')


# --- NEW ROUTES FOR GOOGLE SIGN-IN ---

@bp.route('/google-login', methods=['POST'])
def google_login():
    id_token = request.get_json().get('id_token')
    try:
        # Verify the ID token sent from the client
        decoded_token = firebase_admin_auth.verify_id_token(id_token)
        email = decoded_token['email']
        
        # Check if a user with this email already exists in our Firestore database
        user_data = firebase_service.get_user_by_email(email)
        
        if user_data:
            # User exists, log them in by setting the session and return 'ok' status
            session['leetcode_username'] = user_data['leetcode_username']
            return jsonify({'status': 'ok'})
        else:
            # User is new to our app, tell the frontend to ask for a LeetCode ID
            return jsonify({'status': 'new_user'})
            
    except Exception as e:
        print(f"Google login error: {e}")
        return jsonify({'status': 'error', 'message': 'Invalid authentication token.'}), 401


@bp.route('/google-register', methods=['POST'])
def google_register():
    data = request.get_json()
    id_token = data.get('id_token')
    leetcode_id = data.get('leetcode_id', '').lower()
    
    if not leetcode_id:
        return jsonify({'status': 'error', 'message': 'LeetCode ID is required.'})

    try:
        # Securely verify the token again on the registration step
        decoded_token = firebase_admin_auth.verify_id_token(id_token)
        email = decoded_token['email']
        
        # --- Final Validation Checks ---
        if not leetcode_api.get_user_stats(leetcode_id):
            return jsonify({'status': 'error', 'message': 'Invalid LeetCode username.'})
        if firebase_service.get_user_data(leetcode_id):
            return jsonify({'status': 'error', 'message': 'This LeetCode username is already registered.'})
        if firebase_service.get_user_by_email(email):
            return jsonify({'status': 'error', 'message': 'This email is already registered.'})

        # --- Create the User ---
        # User is verified by Google, so we mark them as verified in our system
        firebase_service.create_unverified_user(leetcode_id, email, "google-verified")
        # Set a random password hash since they won't use a password to log in via Google
        password_hash = generate_password_hash(str(random.randint(1, 10**12)))
        firebase_service.verify_user_and_set_password(leetcode_id, password_hash)
        
        # Log the new user in
        session['leetcode_username'] = leetcode_id
        return jsonify({'status': 'ok'})

    except Exception as e:
        print(f"Google registration error: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred during registration.'}), 401