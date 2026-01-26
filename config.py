import os

class Config:
    # Secret key for sessions
    SECRET_KEY = os.getenv('SECRET_KEY', 'smart-stock-system-2025-vedashree')
    
    # Database logic: Check Cloud first, then check Local
    MYSQL_HOST = os.getenv('MYSQLHOST', 'localhost')
    MYSQL_USER = os.getenv('MYSQLUSER', 'root')
    # Change 'root' below to your actual local XAMPP password if it's different
    MYSQL_PASSWORD = os.getenv('MYSQLPASSWORD', 'root') 
    MYSQL_DB = os.getenv('MYSQLDATABASE', 'smart_stock')
    MYSQL_PORT = int(os.getenv('MYSQLPORT', 3306))
    
    MYSQL_CURSORCLASS = 'DictCursor'
    
    
    @staticmethod
    def init_app(app):
        if not os.path.exists(Config.UPLOAD_FOLDER):
            os.makedirs(Config.UPLOAD_FOLDER)