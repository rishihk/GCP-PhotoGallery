from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import mysql.connector
import boto3
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

db_config = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_DATABASE')
}

# AWS S3 Configuration
app.config['S3_BUCKET'] = os.getenv('S3_BUCKET')
app.config['S3_KEY'] = os.getenv('S3_KEY')
app.config['S3_SECRET'] = os.getenv('S3_SECRET')

# Configure the S3 client
s3_client = boto3.client(
    's3',
    aws_access_key_id=app.config['S3_KEY'],
    aws_secret_access_key=app.config['S3_SECRET']
)

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

@app.route('/')
@app.route('/gallery')
def gallery():
    response = s3_client.list_objects_v2(Bucket=app.config['S3_BUCKET'])
    images = []
    if 'Contents' in response:
        for obj in response['Contents']:
            images.append(f"https://{app.config['S3_BUCKET']}.s3.amazonaws.com/{obj['Key']}")
    
    return render_template('gallery.html', images=images)

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        
        upload_password = request.form.get('upload_password')
        if upload_password != os.getenv('MOD_PASSWORD'):
            return redirect(request.url)
        
        if 'file' not in request.files:
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename):
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

        # No duplicates found; proceed with file upload to S3
        s3_client.upload_fileobj(file, app.config['S3_BUCKET'], filename)
        file_url = f"https://{app.config['S3_BUCKET']}.s3.amazonaws.com/{filename}"
        
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
        return redirect(url_for('gallery'))
    
    # Delete image from S3 bucket
    try:
        s3_client.delete_object(Bucket=app.config['S3_BUCKET'], Key=filename)
    except Exception as e:
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
        return redirect(url_for('gallery'))
    
    return redirect(url_for('gallery'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)