import mysql.connector

try:
    conn = mysql.connector.connect(
        host='localhost',
        user='root',      # Change if different
        password='root',      # Your MySQL password
        database='smart_stock'
    )
    print(" MySQL Connected!")
    
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    print(f" Found {len(users)} users in database")
    
    for user in users:
        print(f"  - Username: {user[1]}, Password: {user[2]}")
    
    conn.close()
    
except Exception as e:
    print(f" MySQL Error: {e}")