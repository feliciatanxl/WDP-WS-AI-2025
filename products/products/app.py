from flask import Flask, render_template, redirect, url_for
import pyodbc

app = Flask(__name__)

# SQL Server connection
conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=CHAR;"
    "DATABASE=ProductApp;"
    "Trusted_Connection=yes;"
)

@app.route("/admin/dashboard")
def admin_dashboard():
    print("\n" + "="*20)
    print("ROUTE IS TRIGGERED!")
    print("="*20 + "\n")
    
    1/0  

    cursor = conn.cursor()
    cursor.execute("SELECT Id, Name, Stock, Price FROM Products ORDER BY Id DESC")
    products = cursor.fetchall()
    
    print(f"I FOUND {len(products)} PRODUCTS") 

    return render_template("admin.html", products=products, inquiries=[])

 

@app.route("/admin/products/delete/<int:id>")
def delete_product(id):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM Products WHERE Id = ?", id)
    conn.commit()
    return redirect(url_for("admin_dashboard"))

if __name__ == "__main__":
    app.run(debug=True)
