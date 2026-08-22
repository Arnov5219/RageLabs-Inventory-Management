# RageLabs Inventory Management

A modern Django-based inventory management system designed for tracking laundry supplies and accessories, featuring real-time stock adjustments, search/filtering, comprehensive audit histories, and seamless Google Sheets integration for daily reporting.

---

## Features

- **Interactive Dashboard**: Real-time stats on total stock, low-stock warnings, and quick-action audit trail logs.
- **Categorized Inventory**:
  - **Laundry Supplies**: Track detergents, fabric softeners, bleach powders, and other consumables.
  - **Laundry Accessories**: Track reusable assets like baskets, hangers, and ironing boards.

---

## Installation & Setup

Follow these steps to set up the project locally.

### 1. Clone and Navigate to the Repository
```bash
git clone <repository-url>
cd RageLabs-Inventory-Management
```

### 2. Create and Activate a Virtual Environment
It is highly recommended to use a virtual environment to manage dependencies.

**On Windows (PowerShell/CMD):**
```powershell
python -m venv venv
.\venv\Scripts\activate
```

### 3. Install Dependencies
Install all required Python libraries using the `requirements.txt` file:
```bash
pip install -r requirements.txt
```

## Quickstart Guide

Get the project up and running in a few simple commands:

### 1. Database Migrations
Initialize the SQLite database schema:
```bash
python manage.py migrate
```

### 2. Create a Superuser (Optional)
To access the Django Admin panel:
```bash
python manage.py createsuperuser
```

### 3. Run the Development Server
Start the local server:
```bash
python manage.py runserver
```

Once the server is running, open your web browser and navigate to:
- **Application Dashboard**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Django Admin Panel**: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

  