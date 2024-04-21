from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import mysql.connector
from google.cloud import storage
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Flask
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

# Database configuration
db_config = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_DATABASE')
}

# Set Google Cloud credentials environment variable
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

# GCP Bucket Configuration
app.config['GCP_BUCKET'] = os.getenv('GCP_BUCKET')

# Configure the GCP Storage client
storage_client = storage.Client()

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(buffered=True)
        cursor.execute('SELECT * FROM User WHERE username = %s', (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and check_password_hash(user[2], password):
            return redirect(url_for('gallery'))
        else:
            flash('Invalid username or password')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(buffered=True)
        
        cursor.execute('SELECT * FROM User WHERE username = %s', (username,))
        if cursor.fetchone():
            flash('Username already exists.')
            return redirect(url_for('signup'))
        
        hashed_password = generate_password_hash(password)
        cursor.execute('INSERT INTO User (username, password) VALUES (%s, %s)', (username, hashed_password))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Signup successful!')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/gallery')
def gallery():
    bucket = storage_client.get_bucket(app.config['GCP_BUCKET'])
    blobs = bucket.list_blobs()
    images = []
    for blob in blobs:
        images.append(f"https://storage.googleapis.com/{app.config['GCP_BUCKET']}/{blob.name}")
    
    return render_template('gallery.html', images=images)

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        
        upload_password = request.form.get('upload_password')
        if upload_password != os.getenv('MOD_PASSWORD'):
            flash('Invalid upload password', 'error')
            return redirect(request.url)
        
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename):
            flash('No selected file or file type not allowed', 'error')
            return redirect(request.url)
        
        filename = secure_filename(file.filename)

        # Database connection setup
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Check for duplicate uploads based on filename
        cursor.execute('SELECT * FROM Image WHERE Title = %s', (filename,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            flash('Duplicate files not allowed', 'error')  
            return redirect(request.url)

        # No duplicates found; proceed with file upload to GCP bucket
        bucket = storage_client.get_bucket(app.config['GCP_BUCKET'])
        blob = bucket.blob(filename)
        blob.upload_from_file(file)
        file_url = f"https://storage.googleapis.com/{app.config['GCP_BUCKET']}/{filename}"
        
        cursor.execute('INSERT INTO Image (Title, Description, Tags, URL) VALUES (%s, %s, %s, %s)', (
            request.form.get('title', 'Untitled'),
            request.form.get('description', ''),
            request.form.get('tags', ''),
            file_url
        ))
        conn.commit()

        # Close DB connection
        cursor.close()
        conn.close()
        
        # Redirect to the gallery page after successful upload
        return redirect(url_for('gallery'))
    
    # Show the upload form for GET requests
    return render_template('upload.html')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/remove_image/<filename>', methods=['POST'])
def remove_image(filename):
    
    remove_password = request.form['remove_password']
    if remove_password != os.getenv('MOD_PASSWORD'):
        flash('Invalid remove password', 'error')
        return redirect(url_for('gallery'))
    
    # Delete image from GCP bucket
    try:
        bucket = storage_client.get_bucket(app.config['GCP_BUCKET'])
        blob = bucket.blob(filename)
        blob.delete()
    except Exception as e:
        flash('Error deleting image', 'error')
        return redirect(url_for('gallery'))

    # Remove image record from database
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM Image WHERE URL LIKE %s', (f'%{filename}',))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        flash('Error deleting image record', 'error')
        return redirect(url_for('gallery'))
    
    return redirect(url_for('gallery'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
