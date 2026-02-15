import os

class Config:
    # Secret key for sessions
    SECRET_KEY = os.getenv('SECRET_KEY', 'smart-stock-system-2025-vedashree')
    
    # Database logic: Check Cloud first, then check Local
    MYSQL_HOST = os.getenv('MYSQLHOST', 'mysql-3af63198-vedashree358-583a.j.aivencloud.com')
    MYSQL_USER = os.getenv('MYSQLUSER', 'avnadmin')
    # Change 'root' below to your actual local XAMPP password if it's different
    MYSQL_PASSWORD = os.getenv('MYSQLPASSWORD', 'AVNS_eKVKKpSgRbkDtX9DHpP') 
    MYSQL_DB = os.getenv('MYSQLDATABASE', 'smart_stock')
    MYSQL_PORT = int(os.getenv('MYSQLPORT') or 18369)
    MYSQL_SSL_CA = os.path.join(os.getcwd(), 'ca.pem') if 'aivencloud.com' in MYSQL_HOST else None
    
    MYSQL_CURSORCLASS = 'DictCursor'
    UPLOAD_FOLDER = 'uploads'
    
    @staticmethod
    def init_app(app):
        if not os.path.exists(Config.UPLOAD_FOLDER):
            os.makedirs(Config.UPLOAD_FOLDER)
