from app import create_app
from app.social import start_flusher

app = create_app()
start_flusher(app)  # here and not in create_app: tests and scripts build apps without a background thread
