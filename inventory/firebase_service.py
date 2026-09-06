import os
import json
import logging
from decimal import Decimal
import firebase_admin
from firebase_admin import credentials, db, firestore

logger = logging.getLogger(__name__)

CRED_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'firebase-credentials.json')

PROJECT_ID = 'laundryrage-inventory'
DATABASE_URL = None

if os.path.exists(CRED_PATH):
    try:
        with open(CRED_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            PROJECT_ID = data.get('project_id', PROJECT_ID)
    except Exception as e:
        logger.debug(f"Error reading firebase credentials file: {e}")

DATABASE_URL = os.getenv(
    'FIREBASE_DATABASE_URL',
    f'https://{PROJECT_ID}-default-rtdb.asia-south1.firebasedatabase.app/'
)

_app_initialized = False

def get_firebase_app():
    global _app_initialized
    if _app_initialized or firebase_admin._apps:
        _app_initialized = True
        return firebase_admin.get_app()

    if not os.path.exists(CRED_PATH):
        logger.info(f"Firebase credentials not found at {CRED_PATH}. Realtime sync disabled.")
        return None

    try:
        cred = credentials.Certificate(CRED_PATH)
        app = firebase_admin.initialize_app(cred, {
            'projectId': PROJECT_ID,
            'databaseURL': DATABASE_URL
        })
        _app_initialized = True
        logger.info(f"Firebase successfully initialized for project {PROJECT_ID}")
        return app
    except Exception as e:
        logger.warning(f"Firebase initialization skipped or failed: {e}")
        return None


def push_stock_update_to_firebase(branch_code, product_id, current_stock, status, base_stock=None, remaining_percentage=None):
    """
    Pushes real-time stock adjustment to Firebase (Realtime DB and/or Firestore).
    Safe & non-blocking: fails gracefully without interrupting core Django stock operations.
    """
    app = get_firebase_app()
    if not app:
        return False

    # Format numeric values cleanly
    try:
        stock_val = float(current_stock) if isinstance(current_stock, (int, float, Decimal)) else float(str(current_stock))
    except (ValueError, TypeError):
        stock_val = 0.0

    payload = {
        'product_id': int(product_id),
        'stock': stock_val,
        'status': str(status or 'In Stock'),
        'base_stock': float(base_stock) if base_stock is not None else None,
        'remaining_percentage': float(remaining_percentage) if remaining_percentage is not None else None,
    }

    pushed = False

    # 1. Try Firebase Realtime Database
    try:
        ref = db.reference(f'branches/{branch_code}/products/{product_id}')
        rtdb_payload = dict(payload)
        rtdb_payload['updated_at'] = {'.sv': 'timestamp'}
        ref.set(rtdb_payload)
        pushed = True
        logger.debug(f"[FIREBASE RTDB] Updated branch {branch_code} product {product_id} -> {stock_val}")
    except Exception as rtdb_err:
        logger.debug(f"[FIREBASE RTDB] Realtime DB sync notice: {rtdb_err}")

    # 2. Try Cloud Firestore
    try:
        fs = firestore.client(app)
        fs_payload = dict(payload)
        fs_payload['updated_at'] = firestore.SERVER_TIMESTAMP
        fs.collection('branches').document(str(branch_code)).collection('products').document(str(product_id)).set(
            fs_payload, merge=True
        )
        pushed = True
        logger.debug(f"[FIREBASE FIRESTORE] Updated branch {branch_code} product {product_id} -> {stock_val}")
    except Exception as fs_err:
        logger.debug(f"[FIREBASE FIRESTORE] Firestore sync notice: {fs_err}")

    return pushed

